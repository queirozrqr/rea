"""Linha de comando ``bbrea``.

    bbrea init <programa>
    bbrea scope-check <programa> <url>
    bbrea web <programa> <url> [--target-id ID] [--observation-ms N] [--cdp URL]
    bbrea apk <programa> <arquivo.apk> [--search Api --search Auth ...]
    bbrea capture <programa> <arquivo.har> [--format har|mitmproxy]
    bbrea js <programa> <diretorio-ou-asar>
    bbrea firmware <programa> <imagem.bin>
    bbrea report <programa> <diretorio-da-execucao>
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from bbrea import pipelines
from bbrea.pipelines import PipelineError
from bbrea.report import write_report
from bbrea.runner import ReaError, ReaRunner
from bbrea.scope import OutOfScope, ScopeError
from bbrea.workspace import Workspace, WorkspaceError, default_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bbrea", description="Recon com REA, escopo primeiro.")
    parser.add_argument("--root", type=Path, default=None, help="BB_WORK_DIR (padrão /srv/bb)")
    parser.add_argument("--timeout", type=int, default=900, help="tempo limite por comando (s)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="cria diretórios e modelo de escopo")
    p.add_argument("program")

    p = sub.add_parser("scope-check", help="verifica se uma URL está no escopo")
    p.add_argument("program")
    p.add_argument("url")

    p = sub.add_parser("web", help="recon de aplicação web aberta no bb-chromium")
    p.add_argument("program")
    p.add_argument("url")
    p.add_argument("--target-id")
    p.add_argument("--observation-ms", type=int, default=5000)
    p.add_argument("--cdp", default=os.environ.get("BB_CDP_ENDPOINT", "http://127.0.0.1:9222"))
    p.add_argument("--no-report", action="store_true")

    p = sub.add_parser("apk", help="manifesto e busca de classes de um APK")
    p.add_argument("program")
    p.add_argument("path")
    p.add_argument("--search", action="append", default=[])

    p = sub.add_parser("capture", help="inspeção offline de HAR/mitmproxy")
    p.add_argument("program")
    p.add_argument("path")
    p.add_argument("--format", choices=["har", "mitmproxy"], default="har")
    p.add_argument("--no-report", action="store_true")

    p = sub.add_parser("js", help="análise estática de app JS/Electron")
    p.add_argument("program")
    p.add_argument("path")

    p = sub.add_parser("firmware", help="regiões de uma imagem de firmware")
    p.add_argument("program")
    p.add_argument("path")

    p = sub.add_parser("report", help="gera report.md higienizado de uma execução")
    p.add_argument("program")
    p.add_argument("run_dir")
    return parser


def _report(ws: Workspace, run_dir: Path) -> None:
    try:
        scope = ws.scope()
    except (OutOfScope, ScopeError):
        scope = None
    print(f"relatório: {write_report(run_dir, scope)}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root or default_root()
    try:
        ws = Workspace(root, args.program)
        if args.cmd == "init":
            for path in ws.init():
                print(f"criado: {path}")
            print(f"edite o escopo: {ws.scope_file}")
            return 0
        if args.cmd == "scope-check":
            rule = ws.scope().check_url(args.url)
            print(f"NO ESCOPO (regra: {rule.raw})")
            return 0
        if args.cmd == "report":
            run_dir = ws.confine(args.run_dir, base=ws.output)
            _report(ws, run_dir)
            return 0

        runner = ReaRunner(timeout_s=args.timeout)
        if args.cmd == "web":
            run_dir = pipelines.web(
                ws, runner, args.url, args.cdp,
                target_id=args.target_id, observation_ms=args.observation_ms,
            )
        elif args.cmd == "apk":
            run_dir = pipelines.apk(ws, runner, args.path, args.search)
        elif args.cmd == "capture":
            run_dir = pipelines.har(ws, runner, args.path, args.format)
        elif args.cmd == "js":
            run_dir = pipelines.javascript(ws, runner, args.path)
        else:
            run_dir = pipelines.firmware(ws, runner, args.path)
        print(f"execução: {run_dir}")
        if not getattr(args, "no_report", False):
            _report(ws, run_dir)
        return 0
    except OutOfScope as exc:
        print(f"FORA DO ESCOPO: {exc}", file=sys.stderr)
        return 3
    except (ScopeError, WorkspaceError, PipelineError, ReaError, ValueError, OSError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
