"""Antibody files: one Semgrep rule per file, with its provenance under `metadata.antibody`."""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

DIR = ".antibodies"
RULE_SUFFIXES = (".yml", ".yaml")
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
# A stamp is rewritten only when one of these changes, so re-verifying doesn't churn files.
PROOF_KEYS = ("proof", "vulnerable", "fixed", "fires_on", "fixtures")

README = """\
# Antibodies

Each `*.yml` file here is a Semgrep rule learned from a real fix: a bug fix, a security
fix, or a correction made to a coding agent. `metadata.antibody` records where it came
from and, once `antibody verify` passes, the proof that it fires on the mistake and not
on the fix. A file with the same name and another extension is a fixture, with `ruleid:`
and `ok:` comments marking what must and must not match. `baseline.json` lists the
matches accepted on purpose, so only new ones fail.

- `antibody check` runs every verified antibody (use it in CI); `--since <ref>` checks
  only what changed.
- `antibody hook claude` runs them on each file Claude Code edits.
- `antibody verify --all` re-proves them (commit proofs need full git history).
- They are plain Semgrep rules, so `semgrep scan --config .antibodies --exclude .antibodies`
  works without antibody installed.
"""


class AntibodyError(ValueError):
    """An antibody file is missing or malformed."""


def _yaml() -> YAML:
    yaml = YAML()  # round-trip mode keeps comments, key order and block scalars
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    yaml.preserve_quotes = True
    return yaml


@dataclass(eq=False)
class Antibody:
    path: Path
    doc: Any

    @property
    def rule(self) -> Any:
        return self.doc["rules"][0]

    @property
    def id(self) -> str:
        return str(self.rule.get("id"))

    @property
    def meta(self) -> Any:
        return (self.rule.get("metadata") or {}).get("antibody") or {}

    @property
    def source(self) -> Any:
        return self.meta.get("source") or {}

    @property
    def verified(self) -> Any:
        return self.meta.get("verified")

    @property
    def kind(self) -> str:
        return str(self.meta.get("kind") or "")

    @property
    def languages(self) -> list[str]:
        return [str(lang) for lang in self.rule.get("languages") or []]

    @property
    def message(self) -> str:
        return " ".join(str(self.rule.get("message") or "").split())

    def fixtures(self) -> list[Path]:
        return sorted(
            p
            for p in self.path.parent.glob(f"{self.path.stem}.*")
            if p.suffix not in RULE_SUFFIXES and p.is_file()
        )

    def set_source_commit(self, commit: str) -> None:
        source = self._antibody_meta().setdefault("source", CommentedMap())
        if source.get("commit") != commit or "base" in source:
            source.pop("base", None)
            source["commit"] = commit
            self.save()

    def pin(self, vulnerable: str, fixed: str, summary: str) -> None:
        """An uncommitted fix was committed: record the commits that prove it from now on."""
        source = self._antibody_meta().setdefault("source", CommentedMap())
        source.pop("base", None)
        source["commit"] = fixed
        source["vulnerable"] = vulnerable
        source.setdefault("summary", summary)
        self.save()

    def write_stamp(self, stamp: dict) -> bool:
        """Record a passing proof. Returns False if the same proof is already recorded."""
        old = _plain(self.verified or {})
        if all(old.get(k) == stamp.get(k) for k in PROOF_KEYS):
            return False
        self._antibody_meta()["verified"] = stamp
        self.save()
        return True

    def save(self) -> None:
        buf = io.StringIO()
        _yaml().dump(self.doc, buf)
        self.path.write_text(buf.getvalue())

    def _antibody_meta(self) -> Any:
        rule = self.rule
        if not isinstance(rule.get("metadata"), dict):
            rule["metadata"] = CommentedMap()
        if not isinstance(rule["metadata"].get("antibody"), dict):
            rule["metadata"]["antibody"] = CommentedMap()
        return rule["metadata"]["antibody"]


def load(path: Path) -> Antibody:
    try:
        doc = _yaml().load(path.read_text())
    except OSError as e:
        raise AntibodyError(f"{path}: {e.strerror}") from None
    except YAMLError as e:
        raise AntibodyError(f"{path}: not valid YAML: {e}") from None
    rules = doc.get("rules") if isinstance(doc, dict) else None
    if not isinstance(rules, list) or len(rules) != 1 or not isinstance(rules[0], dict):
        raise AntibodyError(f"{path}: an antibody holds exactly one rule under `rules:`")
    antibody = Antibody(path, doc)
    if not ID_PATTERN.fullmatch(antibody.id):
        raise AntibodyError(f"{path}: rule id {antibody.id!r} may only use letters, digits, - and _")
    if antibody.id != path.stem:
        raise AntibodyError(f"{path}: rule id {antibody.id!r} must match the file name")
    return antibody


def discover(repo: Path) -> list[Path]:
    folder = repo / DIR
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix in RULE_SUFFIXES and p.is_file())


def resolve_ref(repo: Path, ref: str) -> Path:
    """An antibody id from .antibodies/, or a path to a rule file anywhere."""
    if Path(ref).suffix in RULE_SUFFIXES:
        if Path(ref).is_file():
            return Path(ref).resolve()
        raise AntibodyError(f"no such file: {ref}")
    for suffix in RULE_SUFFIXES:
        path = repo / DIR / f"{ref}{suffix}"
        if path.is_file():
            return path
    raise AntibodyError(f"no antibody named {ref!r} in {DIR}/")


def init_dir(repo: Path) -> list[Path]:
    created = []
    folder = repo / DIR
    if not folder.is_dir():
        folder.mkdir()
        created.append(folder)
    readme = folder / "README.md"
    if not readme.exists():
        readme.write_text(README)
        created.append(readme)
    return created


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))
