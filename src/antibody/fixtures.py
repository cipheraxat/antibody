"""Rule self-tests in Semgrep's annotation style: a `ruleid: <id>` or `ok: <id>` comment
on the line before the code it describes."""

from __future__ import annotations

import re
from pathlib import Path

from .engine import Engine

ANNOTATION = re.compile(r"^\s*(?:#|//|/\*|<!--|--)\s*(ruleid|ok)\s*:\s*([A-Za-z0-9_\-, ]+)")


def expectations(text: str, rule_id: str) -> tuple[set[int], set[int]]:
    """Lines that must match (`ruleid`) and lines that must not (`ok`)."""
    must: set[int] = set()
    must_not: set[int] = set()
    pending: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        annotation = ANNOTATION.match(line)
        if annotation:
            if rule_id in [i.strip() for i in annotation.group(2).split(",")]:
                pending.append(annotation.group(1))
            continue
        for kind in pending:
            (must if kind == "ruleid" else must_not).add(number)
        pending = []
    return must, must_not


def problems(name: str, text: str, rule_id: str, found: set[int]) -> list[str]:
    """Compare the lines a rule matched in a fixture with what its annotations expect."""
    must, must_not = expectations(text, rule_id)
    if not must and not must_not:
        return [f"{name}: no `ruleid: {rule_id}` or `ok: {rule_id}` annotations"]
    out = [f"{name}:{n}: expected a match (ruleid)" for n in sorted(must - found)]
    out += [f"{name}:{n}: matched a line marked ok" for n in sorted(found & must_not)]
    out += [f"{name}:{n}: unannotated match" for n in sorted(found - must - must_not)]
    return out


def check_fixture(engine: Engine, rule: Path, rule_id: str, fixture: Path) -> list[str]:
    found = {
        f.start_line
        for f in engine.scan([rule], fixture.parent, [fixture.name])
        if f.rule_id == rule_id
    }
    return problems(fixture.name, fixture.read_text(errors="replace"), rule_id, found)
