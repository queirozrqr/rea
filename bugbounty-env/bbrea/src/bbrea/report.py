"""Relatório Markdown higienizado a partir das saídas de uma execução.

Extração genérica e conservadora: percorre todos os JSON da execução, coleta
strings que são URLs ou caminhos de API e classifica cada host contra o
escopo. Valores de query string são SEMPRE substituídos por ``REDACTED``,
pois podem conter tokens. Os achados são candidatos para revisão manual.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bbrea.runner import write_private
from bbrea.scope import OutOfScope, Scope, ScopeError

URL_RE = re.compile(r"https?://[^\s\"'<>`]+", re.IGNORECASE)
API_PATH_RE = re.compile(
    r"^/(?:api|v\d+|graphql|gql|rest|internal|admin|private|debug|auth|oauth|_next/data)(?:[/?#]|$)",
    re.IGNORECASE,
)
SOURCE_MAP_RE = re.compile(r"\.map(?:[?#]|$)|sourceMappingURL", re.IGNORECASE)
MAX_STRING = 4096


def redact_url(url: str) -> str:
    """Remove credenciais e substitui os valores da query e o fragmento."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    query = urlencode([(k, "REDACTED") for k, _ in parse_qsl(parts.query, keep_blank_values=True)])
    fragment = "REDACTED" if parts.fragment else ""
    return urlunsplit((parts.scheme, host, parts.path, query, fragment))


def iter_strings(node: Any):
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if len(item) <= MAX_STRING:
                yield item
            else:
                yield from URL_RE.findall(item)
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def collect(run_dir: Path) -> dict[str, Any]:
    urls: set[str] = set()
    api_paths: set[str] = set()
    for path in sorted(run_dir.glob("*.json")):
        if path.name == "summary.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for text in iter_strings(data):
            for match in URL_RE.findall(text):
                urls.add(match.rstrip(").,;"))
            if API_PATH_RE.match(text) and len(text) < 512:
                api_paths.add(text.split("?", 1)[0])
    return {"urls": urls, "api_paths": api_paths}


def classify(urls: set[str], scope: Scope | None) -> dict[str, list[str]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for url in urls:
        try:
            safe = redact_url(url)
        except ValueError:
            continue
        if scope is None:
            groups["sem escopo carregado"].add(safe)
            continue
        try:
            scope.check_url(url)
            groups["no escopo"].add(safe)
        except (OutOfScope, ScopeError):
            groups["fora do escopo (NÃO testar)"].add(safe)
    return {k: sorted(v) for k, v in groups.items()}


def render(run_dir: Path, scope: Scope | None) -> str:
    found = collect(run_dir)
    groups = classify(found["urls"], scope)
    maps = sorted({redact_url(u) for u in found["urls"] if SOURCE_MAP_RE.search(u)})
    summary_path = run_dir / "summary.json"
    steps = []
    if summary_path.is_file():
        steps = json.loads(summary_path.read_text(encoding="utf-8")).get("steps", [])

    lines = [f"# Recon – {run_dir.name}", "", "## Passos executados", ""]
    for step in steps:
        mark = "ok" if step.get("status") == "ok" else f"ERRO: {step.get('error', '')}"
        lines.append(f"- `{step.get('step')}` → {mark} (`{step.get('file')}`)")
    lines += ["", "## Possíveis source maps expostos", ""]
    lines += [f"- {u}" for u in maps] or ["- nenhum candidato"]
    lines += ["", "## Caminhos de API candidatos", ""]
    lines += [f"- `{p}`" for p in sorted(found["api_paths"])] or ["- nenhum candidato"]
    for title, items in sorted(groups.items()):
        lines += ["", f"## URLs – {title} ({len(items)})", ""]
        lines += [f"- {u}" for u in items]
    lines += [
        "",
        "---",
        "Candidatos extraídos automaticamente; confirme cada um manualmente e só teste o que estiver no escopo.",
        "Valores de query string e fragmentos foram substituídos por REDACTED.",
    ]
    return "\n".join(lines) + "\n"


def write_report(run_dir: Path, scope: Scope | None) -> Path:
    out = run_dir / "report.md"
    write_private(out, render(run_dir, scope))
    return out
