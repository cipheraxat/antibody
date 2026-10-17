"""Find and run a Semgrep-compatible engine: Opengrep if installed, otherwise Semgrep CE."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path, PurePosixPath


class EngineError(RuntimeError):
    """The engine is missing, rejected a rule, or crashed."""


@dataclass(frozen=True)
class Finding:
    rule_id: str
    path: str  # relative to the scan root, with forward slashes
    start_line: int
    end_line: int

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}"


def locations(findings: list[Finding]) -> str:
    return ", ".join(f.location for f in findings)


@dataclass(frozen=True)
class Engine:
    name: str  # "opengrep" or "semgrep"
    binary: str

    @cached_property
    def version(self) -> str:
        # Asked for lazily: `semgrep --version` costs a full Python start, too slow for a hook.
        proc = subprocess.run([self.binary, "--version"], capture_output=True, text=True, check=False)
        match = re.search(r"\d+\.\d+\.\d+", proc.stdout + proc.stderr)
        return match.group(0) if match else "unknown"

    @property
    def label(self) -> str:
        return f"{self.name} {self.version}"

    def scan(
        self,
        rules: list[Path],
        root: Path,
        targets: list[str] | None = None,
        exclude: list[str] | None = None,
        sarif: Path | None = None,
    ) -> list[Finding]:
        """Run `rules` over `targets`, given relative to `root`. None scans all of `root`."""
        if targets is not None and not targets:
            return []
        args = ["--json", "--quiet"]
        if self.name == "semgrep":
            # A security tool should not phone home, and the update check is noise.
            args += ["--metrics=off", "--disable-version-check"]
        for rule in rules:
            args += ["--config", str(rule)]
        for pattern in exclude or []:
            args += ["--exclude", pattern]
        if sarif:
            args.append(f"--sarif-output={sarif}")
        args += targets if targets is not None else ["."]
        if not sarif:
            # Both engines' OCaml CLI (--experimental) starts several times faster than the
            # Python one, which matters in an edit hook. It skips --sarif-output silently, and
            # if it refuses anything else we fall back to the Python CLI.
            try:
                return self._run(["scan", "--experimental", *args], root)
            except EngineError:
                pass
        return self._run(["scan", *args], root)

    def _run(self, args: list[str], root: Path) -> list[Finding]:
        proc = subprocess.run(
            [self.binary, *args], cwd=root, capture_output=True, text=True, check=False
        )
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise EngineError(f"{self.name} exited with {proc.returncode}: {detail}") from None
        errors = [e for e in out.get("errors", []) if e.get("level") == "error"]
        if errors:
            raise EngineError("; ".join(str(e.get("message") or e.get("type")) for e in errors))
        if proc.returncode not in (0, 1):
            raise EngineError(f"{self.name} exited with {proc.returncode}: {proc.stderr.strip()}")

        return [
            Finding(
                # Semgrep prefixes rule ids with the rule file's path; antibody ids have no dots.
                rule_id=r["check_id"].rsplit(".", 1)[-1],
                path=str(PurePosixPath(r["path"])),
                start_line=r["start"]["line"],
                end_line=r["end"]["line"],
            )
            for r in out.get("results", [])
        ]


def find_engine(name: str | None = None) -> Engine:
    """`name` or $ANTIBODY_ENGINE if given. Otherwise the engine installed with antibody (the
    [semgrep] extra), then opengrep, then semgrep from PATH."""
    wanted = name or os.environ.get("ANTIBODY_ENGINE")
    if wanted:
        binary = _beside(wanted) or _on_path(wanted)
        if not binary:
            raise EngineError(f"rule engine {wanted!r} not found")
        return _engine(binary)
    for binary in (_beside("semgrep"), _beside("opengrep"), _on_path("opengrep"), _on_path("semgrep")):
        if binary:
            return _engine(binary)
    raise EngineError(
        "no rule engine found: install opengrep, or reinstall with `uv tool install 'antibody[semgrep]'`"
    )


def _engine(binary: str) -> Engine:
    return Engine("opengrep" if "opengrep" in Path(binary).name else "semgrep", binary)


def _beside(name: str) -> str | None:
    # An engine installed as our own extra sits beside the interpreter and may not be on PATH.
    beside = Path(sys.executable).parent / name
    return str(beside) if "/" not in name and beside.is_file() else None


def _on_path(name: str) -> str | None:
    if "/" in name or os.sep in name:
        return name if Path(name).is_file() else None
    return shutil.which(name)
