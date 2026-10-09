"""Pipelines de recon que encadeiam comandos do REA.

Cada execução grava em ``output/<programa>/<UTC>-<tipo>/``:
- ``NN-<comando>.json``: saída bruta ``--json`` de cada passo (modo 600);
- ``summary.json``: passos, status e erros.

Somente os nomes de campos documentados no contrato do REA são lidos
(``list_browser_targets`` -> ``targets[].target_id`` / ``targets[].url``);
o restante da saída é preservado sem interpretação.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bbrea.runner import ReaError, ReaRunner, validate_cdp_endpoint, write_private
from bbrea.workspace import Workspace


class PipelineError(RuntimeError):
    """Um passo obrigatório falhou ou a seleção do alvo é ambígua."""


@dataclass
class Recorder:
    """Executa passos, grava saídas e mantém o resumo da execução."""

    runner: ReaRunner
    run_dir: Path
    steps: list[dict[str, Any]] = field(default_factory=list)

    def output_path(self, name: str) -> Path:
        return self.run_dir / f"{len(self.steps) + 1:02d}-{name}.json"

    def step(self, name: str, args: Sequence[str], *, required: bool = False) -> Any:
        out = self.output_path(name)
        entry: dict[str, Any] = {"step": name, "args": list(args), "file": out.name}
        try:
            payload = self.runner.run(args, save_to=out)
            entry["status"] = "ok"
            return payload
        except ReaError as exc:
            entry.update(status="error", error=str(exc), returncode=exc.returncode)
            if required:
                raise PipelineError(f"passo obrigatório '{name}' falhou: {exc}") from exc
            return None
        finally:
            self.steps.append(entry)

    def finish(self, **extra: Any) -> Path:
        summary = {"run_dir": str(self.run_dir), "steps": self.steps, **extra}
        path = self.run_dir / "summary.json"
        write_private(path, json.dumps(summary, ensure_ascii=False, indent=2))
        return path


def iter_targets(payload: Any) -> Iterator[dict[str, Any]]:
    """Encontra ``targets[]`` com ``target_id`` em qualquer nível do JSON."""
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            targets = node.get("targets")
            if isinstance(targets, list):
                for item in targets:
                    if isinstance(item, dict) and isinstance(item.get("target_id"), str):
                        yield item
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    return (parts.scheme.lower(), (parts.hostname or "").lower(), parts.port)


def select_target(payload: Any, url: str, target_id: str | None = None) -> dict[str, Any]:
    """Escolhe a aba do navegador: por ID explícito, URL exata ou mesma origem."""
    targets = list({t["target_id"]: t for t in iter_targets(payload)}.values())
    if target_id is not None:
        for target in targets:
            if target["target_id"] == target_id:
                return target
        raise PipelineError(f"target_id {target_id!r} não encontrado")
    exact = [t for t in targets if t.get("url") == url]
    if len(exact) == 1:
        return exact[0]
    same_origin = [t for t in targets if _origin(str(t.get("url", ""))) == _origin(url)]
    candidates = exact or same_origin
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise PipelineError(f"nenhuma aba aberta em {url}; abra com bb-chromium primeiro")
    ids = ", ".join(f"{t['target_id']} ({t.get('url')})" for t in candidates)
    raise PipelineError(f"várias abas candidatas; use --target-id. Candidatas: {ids}")


def web(
    ws: Workspace,
    runner: ReaRunner,
    url: str,
    cdp_endpoint: str,
    *,
    target_id: str | None = None,
    observation_ms: int = 5000,
) -> Path:
    """Recon de aplicação web: bundle, captura passiva, exportação e análise do JS."""
    scope = ws.scope()
    scope.check_url(url)
    cdp = validate_cdp_endpoint(cdp_endpoint)
    rec = Recorder(runner, ws.new_run_dir("web"))

    listing = rec.step("list-browser-targets", ["list-browser-targets", cdp], required=True)
    target = select_target(listing, url, target_id)
    # A aba pode ter sido redirecionada: revalida a URL atual contra o escopo.
    scope.check_url(str(target.get("url", "")))
    tid = target["target_id"]

    rec.step("analyze-web-bundle", ["analyze-web-bundle", cdp, tid])
    capture_file = rec.output_path("inspect-web-page")
    capture = rec.step(
        "inspect-web-page",
        [
            "inspect-web-page", cdp, tid,
            "--observation-ms", str(observation_ms),
            "--include-script-sources",
            "--include-json-body-shapes",
            "--include-websocket-shapes",
        ],
    )
    if capture is not None:
        scripts_dir = rec.run_dir / "scripts"  # precisa NÃO existir (exigência do REA)
        exported = rec.step("export-web-scripts", ["export-web-scripts", str(capture_file), str(scripts_dir)])
        files_dir = scripts_dir / "files"
        if exported is not None and files_dir.is_dir():
            rec.step("analyze-javascript-application", ["analyze-javascript-application", str(files_dir)])

    rec.finish(kind="web", url=url, target=target)
    return rec.run_dir


def apk(ws: Workspace, runner: ReaRunner, apk_path: str, queries: Sequence[str] = ()) -> Path:
    """Manifesto do APK e buscas de classes (ex.: Api, Auth, WebView, Deeplink)."""
    path = ws.confine(apk_path)
    rec = Recorder(runner, ws.new_run_dir("apk"))
    rec.step("inspect-android-package", ["inspect-android-package", str(path)], required=True)
    for query in queries:
        rec.step("search-android-classes", ["search-android-classes", str(path), query])
    rec.finish(kind="apk", target=str(path), queries=list(queries))
    return rec.run_dir


def har(ws: Workspace, runner: ReaRunner, capture_path: str, fmt: str = "har") -> Path:
    """Inspeção offline de HAR ou captura nativa do mitmproxy."""
    if fmt not in ("har", "mitmproxy"):
        raise PipelineError("formato deve ser 'har' ou 'mitmproxy'")
    try:
        path = ws.confine(capture_path)
    except ValueError:
        path = ws.confine(capture_path, base=ws.captures)
    rec = Recorder(runner, ws.new_run_dir("capture"))
    rec.step("inspect-web-network-capture", ["inspect-web-network-capture", str(path), fmt], required=True)
    rec.finish(kind="capture", target=str(path), format=fmt)
    return rec.run_dir


def javascript(ws: Workspace, runner: ReaRunner, app_path: str) -> Path:
    """Análise estática de app JavaScript/Electron (diretório extraído ou .asar)."""
    path = ws.confine(app_path)
    rec = Recorder(runner, ws.new_run_dir("js"))
    rec.step("analyze-javascript-application", ["analyze-javascript-application", str(path)], required=True)
    rec.finish(kind="js", target=str(path))
    return rec.run_dir


def firmware(ws: Workspace, runner: ReaRunner, image_path: str) -> Path:
    """Regiões de firmware (Binwalk). Extração fica a cargo do analista."""
    path = ws.confine(image_path)
    rec = Recorder(runner, ws.new_run_dir("firmware"))
    rec.step("inspect-firmware-regions", ["inspect-firmware-regions", str(path)], required=True)
    rec.finish(kind="firmware", target=str(path))
    return rec.run_dir
