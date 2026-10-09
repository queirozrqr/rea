"""Verificação de escopo de programas de bug bounty.

Formato do arquivo ``scope/<programa>.txt`` (uma regra por linha):

    # comentário
    app.example.com        host exato
    *.example.com          qualquer subdomínio (NÃO inclui o apex)
    203.0.113.10           IP exato
    198.51.100.0/24        rede CIDR
    !admin.example.com     exclusão do host E dos seus subdomínios – sempre vence
    !*.corp.example.com    exclusão por curinga

Política: negação por padrão. Arquivo vazio ou ausente => nada está no escopo.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})

IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class ScopeError(ValueError):
    """Regra de escopo ou URL malformada."""


class OutOfScope(PermissionError):
    """O alvo não está autorizado pelo escopo do programa."""


def normalize_host(host: str) -> str:
    """Normaliza um hostname: minúsculas, sem ponto final, IDNA em ASCII."""
    host = host.strip().rstrip(".").lower()
    if not host or any(c.isspace() for c in host) or "/" in host or "\\" in host:
        raise ScopeError(f"host inválido: {host!r}")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ScopeError(f"host não codificável em IDNA: {host!r}") from exc
    labels = ascii_host.split(".")
    if any(not label or len(label) > 63 for label in labels) or len(ascii_host) > 253:
        raise ScopeError(f"host inválido: {host!r}")
    return ascii_host


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


@dataclass(frozen=True)
class Rule:
    """Uma regra de escopo já validada."""

    raw: str
    exclude: bool
    host: str | None = None
    wildcard: bool = False
    network: IpNetwork | None = None

    @classmethod
    def parse(cls, line: str) -> Rule:
        raw = line.strip()
        exclude = raw.startswith("!")
        body = raw[1:].strip() if exclude else raw
        if not body:
            raise ScopeError(f"regra vazia: {line!r}")
        if "://" in body or ("/" in body and not _looks_like_cidr(body)):
            raise ScopeError(f"use host, *.dominio, IP ou CIDR (sem esquema/caminho): {line!r}")
        if _looks_like_cidr(body) or _parse_ip(body) is not None:
            try:
                network = ipaddress.ip_network(body, strict=True)
            except ValueError as exc:
                raise ScopeError(f"IP/CIDR inválido: {line!r}") from exc
            return cls(raw=raw, exclude=exclude, network=network)
        if body.startswith("*."):
            return cls(raw=raw, exclude=exclude, host=normalize_host(body[2:]), wildcard=True)
        if "*" in body:
            raise ScopeError(f"curinga só é aceito como prefixo '*.': {line!r}")
        return cls(raw=raw, exclude=exclude, host=normalize_host(body))

    def matches(self, host: str) -> bool:
        ip = _parse_ip(host)
        if self.network is not None:
            return ip is not None and ip in self.network
        if ip is not None or self.host is None:
            return False
        if self.wildcard:
            return host.endswith("." + self.host)
        if self.exclude:
            # Conservador: excluir um host exclui também seus subdomínios.
            return host == self.host or host.endswith("." + self.host)
        return host == self.host


def _looks_like_cidr(text: str) -> bool:
    if text.count("/") != 1:
        return False
    addr, _, prefix = text.partition("/")
    return prefix.isdigit() and _parse_ip(addr) is not None


@dataclass(frozen=True)
class Scope:
    """Conjunto de regras de um programa."""

    rules: tuple[Rule, ...]

    @classmethod
    def parse(cls, text: str) -> Scope:
        rules = []
        for number, line in enumerate(text.splitlines(), start=1):
            content = line.split("#", 1)[0].strip()
            if not content:
                continue
            try:
                rules.append(Rule.parse(content))
            except ScopeError as exc:
                raise ScopeError(f"linha {number}: {exc}") from exc
        return cls(tuple(rules))

    @classmethod
    def from_file(cls, path: Path) -> Scope:
        if not path.is_file():
            raise OutOfScope(f"arquivo de escopo ausente: {path} (negação por padrão)")
        return cls.parse(path.read_text(encoding="utf-8"))

    def check_host(self, host: str) -> Rule:
        """Retorna a regra que autoriza ``host`` ou levanta ``OutOfScope``."""
        ip = _parse_ip(host)
        norm = ip.compressed if ip is not None else normalize_host(host)
        for rule in self.rules:
            if rule.exclude and rule.matches(norm):
                raise OutOfScope(f"{norm} excluído por '{rule.raw}'")
        for rule in self.rules:
            if not rule.exclude and rule.matches(norm):
                return rule
        raise OutOfScope(f"{norm} não está no escopo")

    def check_url(self, url: str) -> Rule:
        """Valida esquema e sintaxe da URL e então o host contra o escopo."""
        if any(c.isspace() or c == "\\" for c in url):
            raise ScopeError("URL com espaço ou barra invertida é recusada (ambígua entre parsers)")
        parts = urlsplit(url)
        if parts.scheme.lower() not in ALLOWED_SCHEMES:
            raise ScopeError(f"esquema não permitido: {parts.scheme!r}")
        try:
            _ = parts.port  # valida a porta
        except ValueError as exc:
            raise ScopeError(f"porta inválida em {url!r}") from exc
        if not parts.hostname:
            raise ScopeError(f"URL sem host: {url!r}")
        return self.check_host(parts.hostname)


SCOPE_TEMPLATE = """\
# Escopo do programa – copie EXATAMENTE da página do programa.
# Negação por padrão: só o que estiver listado aqui é permitido.
#
# app.example.com
# *.api.example.com
# !admin.example.com
"""
