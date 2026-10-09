"""Layout do workspace por programa, com confinamento de caminhos."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bbrea.scope import SCOPE_TEMPLATE, Scope

PROGRAM_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
KIND_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
DIR_MODE = 0o700


class WorkspaceError(ValueError):
    """Nome de programa ou caminho fora do workspace."""


def default_root() -> Path:
    return Path(os.environ.get("BB_WORK_DIR", "/srv/bb"))


@dataclass(frozen=True)
class Workspace:
    """Diretórios de um programa dentro de ``BB_WORK_DIR``."""

    root: Path
    program: str

    def __post_init__(self) -> None:
        if not PROGRAM_RE.fullmatch(self.program):
            raise WorkspaceError(
                f"nome de programa inválido: {self.program!r} (use a-z, 0-9, '-', '_')"
            )

    @property
    def targets(self) -> Path:
        return self.root / "targets" / self.program

    @property
    def captures(self) -> Path:
        return self.root / "captures" / self.program

    @property
    def output(self) -> Path:
        return self.root / "output" / self.program

    @property
    def scope_file(self) -> Path:
        return self.root / "scope" / f"{self.program}.txt"

    def init(self) -> list[Path]:
        """Cria os diretórios (modo 700) e um modelo de escopo, sem sobrescrever."""
        created = []
        for directory in (self.targets, self.captures, self.output, self.scope_file.parent):
            if not directory.exists():
                directory.mkdir(mode=DIR_MODE, parents=True)
                created.append(directory)
        if not self.scope_file.exists():
            fd = os.open(self.scope_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(SCOPE_TEMPLATE)
            created.append(self.scope_file)
        return created

    def scope(self) -> Scope:
        return Scope.from_file(self.scope_file)

    def new_run_dir(self, kind: str) -> Path:
        """Cria ``output/<programa>/<UTC>-<kind>`` exclusivo (falha se já existir)."""
        if not KIND_RE.fullmatch(kind):
            raise WorkspaceError(f"tipo de execução inválido: {kind!r}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = self.output / f"{stamp}-{kind}"
        self.output.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        run_dir.mkdir(mode=DIR_MODE)
        return run_dir

    def confine(self, path: str | os.PathLike[str], base: Path | None = None) -> Path:
        """Resolve ``path`` e exige que fique dentro de ``base`` (padrão: targets).

        Links simbólicos são resolvidos antes da comparação, então um link que
        aponte para fora do workspace é recusado.
        """
        base_resolved = (base or self.targets).resolve()
        resolved = Path(path).resolve(strict=True)
        if not resolved.is_relative_to(base_resolved):
            raise WorkspaceError(f"{resolved} está fora de {base_resolved}")
        return resolved
