"""Execução segura da CLI do REA.

- argumentos sempre em lista (``shell=False``), sem NUL;
- tempo limite por chamada;
- saída ``--json`` validada e gravada com modo 600, sem sobrescrever.
"""

from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DEFAULT_TIMEOUT_S = 900


class ReaError(RuntimeError):
    """O REA terminou com falha (status != 0) ou retornou saída ilegível."""

    def __init__(self, message: str, *, returncode: int | None = None, payload: Any = None):
        super().__init__(message)
        self.returncode = returncode
        self.payload = payload


def validate_cdp_endpoint(endpoint: str) -> str:
    """Aceita somente ``http://<loopback literal>:<porta>`` (mesma regra do REA)."""
    parts = urlsplit(endpoint)
    if parts.scheme != "http" or parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError(f"endpoint CDP deve ser http://127.0.0.1:PORTA: {endpoint!r}")
    if parts.username or parts.password or parts.port is None or not parts.hostname:
        raise ValueError(f"endpoint CDP deve ter host loopback e porta explícita: {endpoint!r}")
    try:
        loopback = ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ValueError(f"endpoint CDP precisa ser IP de loopback literal: {endpoint!r}")
    return f"http://{parts.netloc}"


def write_private(path: Path, data: str) -> None:
    """Grava ``data`` em ``path`` com modo 600; falha se o arquivo já existir."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(data)


@dataclass
class ReaRunner:
    """Executa ``rea <comando> ... --json`` e devolve o JSON decodificado."""

    executable: str | None = None
    timeout_s: int = DEFAULT_TIMEOUT_S

    def __post_init__(self) -> None:
        exe = self.executable or os.environ.get("BB_REA") or shutil.which("rea")
        if not exe:
            raise FileNotFoundError("executável 'rea' não encontrado no PATH")
        self.executable = exe

    def command(self, args: Sequence[str]) -> list[str]:
        for arg in args:
            if not isinstance(arg, str) or "\x00" in arg:
                raise ValueError(f"argumento inválido: {arg!r}")
        if not self.executable:
            raise FileNotFoundError("executável 'rea' não configurado")
        return [self.executable, *args, "--json"]

    def run(self, args: Sequence[str], save_to: Path | None = None) -> Any:
        cmd = self.command(args)
        try:
            proc = subprocess.run(  # noqa: S603 - lista de argumentos, sem shell
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReaError(f"tempo limite ({self.timeout_s}s) em: rea {args[0]}") from exc

        if save_to is not None and proc.stdout:
            write_private(save_to, proc.stdout)

        payload: Any = None
        if proc.stdout.strip():
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                if proc.returncode == 0:
                    raise ReaError(f"saída não-JSON de rea {args[0]}") from exc
        if proc.returncode != 0:
            tail = proc.stderr.strip().splitlines()[-5:]
            raise ReaError(
                f"rea {args[0]} falhou (status {proc.returncode}): {' | '.join(tail)}",
                returncode=proc.returncode,
                payload=payload,
            )
        return payload
