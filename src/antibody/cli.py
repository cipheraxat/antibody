"""Command line: antibody init | learn | verify | sweep | baseline | check | list | hook."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import Counter
from importlib import resources
from pathlib import Path, PurePosixPath

from . import __version__, baseline, claude_settings, gitutil, hook
from .engine import Engine, EngineError, Finding, find_engine, locations
from .learn import learn
from .rules import DIR, Antibody, AntibodyError, discover, init_dir, load, resolve_ref
from .verify import (
    DEFAULT_WINDOW,
    FIXTURES_ONLY,
    WORKTREE,
    Proof,
    counts_for_proof,
    prove,
)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.run(args)
    except (AntibodyError, EngineError, gitutil.GitError) as e:
        print(f"antibody: {e}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    repo_opt = argparse.ArgumentParser(add_help=False)
    repo_opt.add_argument("--repo", default=".", help="git repository to work in (default: here)")
    engine_opt = argparse.ArgumentParser(add_help=False)
    engine_opt.add_argument(
        "--engine", help="opengrep, semgrep, or a path to either (default: whichever is installed)"
    )

    parser = argparse.ArgumentParser(
        prog="antibody",
        description="Turn every fix into a verified rule that stops the mistake coming back.",
    )
    parser.add_argument("--version", action="version", version=f"antibody {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("init", parents=[repo_opt], help=f"create {DIR}/ and set up an agent")
    p.add_argument(
        "--agent", choices=["claude"], help="install the skill and the edit hook for this agent"
    )
    p.add_argument("--skill", action="store_true", help="install only the agent skill")
    p.set_defaults(run=cmd_init)

    p = sub.add_parser("learn", parents=[repo_opt], help="write a skeleton and a brief from a fix")
    p.add_argument(
        "commit", nargs="?", help="the fix (default: uncommitted changes if any, else HEAD)"
    )
    p.add_argument("--id", help="antibody id (default: from the commit subject)")
    p.add_argument(
        "--fixtures-only",
        action="store_true",
        help="the mistake never reached git: the fixture alone proves the rule",
    )
    p.set_defaults(run=cmd_learn)

    p = sub.add_parser(
        "verify",
        parents=[repo_opt, engine_opt],
        help="prove antibodies fire on the mistake and not on the fix",
    )
    p.add_argument("ids", nargs="*", metavar="ID", help="antibody ids or rule files")
    p.add_argument("--all", action="store_true", help=f"verify everything in {DIR}/")
    p.add_argument("--fix", metavar="COMMIT", help="record COMMIT as the fix to prove against")
    p.add_argument(
        "--window",
        type=int,
        default=DEFAULT_WINDOW,
        help="max lines between a match and the change (default: %(default)s)",
    )
    p.add_argument("--no-stamp", action="store_true", help="don't record the proof in the file")
    p.add_argument("--json", action="store_true")
    p.set_defaults(run=cmd_verify)

    p = sub.add_parser(
        "sweep", parents=[repo_opt, engine_opt], help="list every match of one antibody"
    )
    p.add_argument("id", help="antibody id or rule file")
    p.add_argument("paths", nargs="*", help="limit the sweep to these paths")
    p.add_argument("--json", action="store_true")
    p.set_defaults(run=cmd_sweep)

    p = sub.add_parser(
        "baseline",
        parents=[repo_opt, engine_opt],
        help="accept the current matches so only new ones fail",
    )
    p.add_argument("ids", nargs="*", metavar="ID", help="antibodies to baseline (default: all)")
    p.set_defaults(run=cmd_baseline)

    p = sub.add_parser(
        "check",
        parents=[repo_opt, engine_opt],
        help="run every verified antibody; exit 1 on new matches (for CI)",
    )
    p.add_argument("paths", nargs="*", help="limit the check to these paths")
    p.add_argument("--since", metavar="REF", help="only check what changed since REF")
    p.add_argument("--no-baseline", action="store_true", help="count accepted matches as new")
    p.add_argument("--include-unverified", action="store_true")
    p.add_argument("--sarif", type=Path, metavar="FILE", help="also write SARIF to FILE")
    p.add_argument("--json", action="store_true")
    p.set_defaults(run=cmd_check)

    p = sub.add_parser("list", parents=[repo_opt], help=f"show what's in {DIR}/")
    p.add_argument("--json", action="store_true")
    p.set_defaults(run=cmd_list)

    p = sub.add_parser(
        "hook", parents=[engine_opt], help="run as an agent's edit hook (event on stdin)"
    )
    p.add_argument("agent", choices=["claude"])
    p.set_defaults(run=cmd_hook)
    return parser


def cmd_init(args: argparse.Namespace) -> int:
    repo = gitutil.toplevel(Path(args.repo))
    done = [f"created {p.relative_to(repo)}" for p in init_dir(repo)]
    if args.skill or args.agent == "claude":
        skill = repo / ".claude" / "skills" / "antibody" / "SKILL.md"
        if not skill.exists():
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_text(resources.files("antibody").joinpath("skill/SKILL.md").read_text())
            done.append(f"created {skill.relative_to(repo)}")
    if args.agent == "claude":
        settings = repo / ".claude" / "settings.json"
        existed = settings.exists()
        if claude_settings.install_hook(settings):
            verb = "updated" if existed else "created"
            done.append(f"{verb} {settings.relative_to(repo)} (runs `antibody hook claude` after edits)")
        if not shutil.which("antibody"):
            done.append(
                "warning: `antibody` isn't on PATH, so the hook can't run yet. "
                "Install it with `uv tool install`."
            )
    print("\n".join(done) or "already set up")
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    repo = gitutil.toplevel(Path(args.repo))
    print(learn(repo, args.commit, args.id, args.fixtures_only).text)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    repo = gitutil.toplevel(Path(args.repo))
    if args.all == bool(args.ids):
        raise AntibodyError("name the antibodies to verify, or pass --all")
    paths = discover(repo) if args.all else [resolve_ref(repo, ref) for ref in args.ids]
    if args.fix and len(paths) != 1:
        raise AntibodyError("--fix applies to exactly one antibody")
    if not paths:
        print(f"nothing to verify in {DIR}/")
        return 0
    engine = find_engine(args.engine)

    results: list[tuple[Antibody | Path, Proof | str, bool]] = []
    for path in paths:
        try:
            antibody = load(path)
            if args.fix:
                antibody.set_source_commit(gitutil.resolve(repo, args.fix))
            proof = prove(antibody, repo, engine, args.window)
        except (AntibodyError, gitutil.GitError) as e:
            if not args.all:
                raise
            results.append((path, str(e), False))  # keep going: one bad antibody shouldn't hide the rest
            continue
        stamped = False
        if proof.passed and not args.no_stamp:
            if proof.revisions.pin:
                antibody.pin(proof.revisions.vulnerable, proof.revisions.fixed, proof.subject)
            stamped = antibody.write_stamp(proof.stamp(engine))
        results.append((antibody, proof, stamped))

    if args.json:
        print(json.dumps([_proof_json(*r) for r in results], indent=2))
    else:
        for result in results:
            _print_proof(repo, engine, *result)
        if len(results) == 1 and isinstance(results[0][1], Proof) and results[0][1].passed:
            print(f"next: antibody sweep {results[0][0].id}")
    return 0 if all(isinstance(p, Proof) and p.passed for _, p, _ in results) else 1


def cmd_sweep(args: argparse.Namespace) -> int:
    repo = gitutil.toplevel(Path(args.repo))
    antibody = load(resolve_ref(repo, args.id))
    engine = find_engine(args.engine)
    findings = [
        f
        for f in engine.scan([antibody.path], repo, _targets(repo, args.paths), exclude=[DIR])
        if f.rule_id == antibody.id
    ]
    if args.json:
        print(json.dumps([_finding_json(repo, f) for f in findings], indent=2))
        return 0
    print(f"{antibody.id}: {_count(len(findings), 'match', 'matches')}")
    lines: dict[Path, list[str]] = {}
    for finding in findings:
        print(f"  {finding.location}  {_code(repo, finding, lines)}")
    if findings:
        print(
            "Fix the real repeats; accept the rest with "
            f"`antibody baseline {antibody.id}` so only new matches fail."
        )
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    repo = gitutil.toplevel(Path(args.repo))
    if args.ids:
        antibodies = [load(resolve_ref(repo, ref)) for ref in args.ids]
    else:
        antibodies = [a for a in map(load, discover(repo)) if a.verified]
    if not antibodies:
        print("no verified antibodies to baseline")
        return 0
    ids = {a.id for a in antibodies}
    engine = find_engine(args.engine)
    found = engine.scan([a.path for a in antibodies], repo, None, exclude=[DIR])
    counts = baseline.tally(baseline.keyed([f for f in found if f.rule_id in ids], repo))
    path = baseline.save(repo, counts, ids)
    print(
        f"accepted {_count(sum(counts.values()), 'match', 'matches')} from "
        f"{_count(len(ids), 'antibody', 'antibodies')} in {_rel(path, repo)}"
    )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    repo = gitutil.toplevel(Path(args.repo))
    if args.since and args.sarif:
        raise AntibodyError("--sarif can't be combined with --since yet")
    antibodies = [load(p) for p in discover(repo)]
    active = [a for a in antibodies if a.verified or args.include_unverified]
    skipped = len(antibodies) - len(active)
    ids = {a.id for a in active}
    accepted = Counter() if args.no_baseline else baseline.load(repo)
    new: list[Finding] = []
    not_new = stale = 0
    if active:
        engine = find_engine(args.engine)
        rules = [a.path for a in active]
        targets = _targets(repo, args.paths)
        if args.since:
            rev = gitutil.resolve(repo, args.since)
            paths = [
                c.new_path
                for c in gitutil.changed_files(repo, rev, gitutil.WORKTREE)
                if c.new_path and counts_for_proof(c.new_path) and _within(c.new_path, targets)
            ]
            now, then = baseline.scan_against(engine, rules, repo, rev, paths)
            now = [(key, f) for key, f in now if f.rule_id in ids]
            new = baseline.new_matches(now, then | accepted)
        else:
            sarif = args.sarif.resolve() if args.sarif else None
            found = engine.scan(rules, repo, targets, exclude=[DIR], sarif=sarif)
            now = baseline.keyed([f for f in found if f.rule_id in ids], repo)
            new = baseline.new_matches(now, accepted)
            if targets is None:
                stale = baseline.stale(accepted, baseline.tally(now), ids)
        not_new = len(now) - len(new)

    if args.json:
        report = {
            "antibodies": len(active),
            "skipped_unverified": skipped,
            "new": [_finding_json(repo, f) for f in new],
            "not_new": not_new,
            "stale_baseline": stale,
        }
        print(json.dumps(report, indent=2))
    else:
        lines: dict[Path, list[str]] = {}
        for finding in new:
            print(f"{finding.location}  [{finding.rule_id}]  {_code(repo, finding, lines)}")
        summary = (
            f"{_count(len(new), 'new match', 'new matches')} from "
            f"{_count(len(active), 'antibody', 'antibodies')}"
        )
        if not_new:
            summary += f" ({not_new} accepted or older)"
        print(("✗ " if new else "✓ ") + summary)
        if stale:
            print(
                f"  {_count(stale, 'accepted match is', 'accepted matches are')} gone; "
                "run `antibody baseline` to shrink the baseline"
            )
        if skipped:
            print(
                f"  {_count(skipped, 'unverified antibody', 'unverified antibodies')} skipped; "
                "verify to enforce"
            )
    return 1 if new else 0


def cmd_list(args: argparse.Namespace) -> int:
    repo = gitutil.toplevel(Path(args.repo))
    rows = []
    for path in discover(repo):
        try:
            a = load(path)
        except AntibodyError as e:
            rows.append({"id": path.stem, "error": str(e)})
            continue
        stamp = a.verified or {}
        rows.append(
            {
                "id": a.id,
                "verified": bool(stamp),
                "proof": str(stamp.get("proof") or ("commit" if stamp else "")),
                "kind": a.kind,
                "fix": str(a.source.get("commit") or "")[:12],
                "languages": a.languages,
                "fixtures": len(a.fixtures()),
            }
        )
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no antibodies yet: fix a mistake, then run `antibody learn`")
        return 0
    for row in rows:
        if "error" in row:
            print(f"✗ {row['error']}")
            continue
        mark = "✓" if row["verified"] else "·"
        print(
            f"{mark} {row['id']:<36} {row['proof'] or '-':<9} {row['fix'] or '-':<12}  "
            f"{row['kind'] or '-':<10}  {', '.join(row['languages'])}"
        )
    print("\n✓ verified  · not verified yet")
    return 0


def cmd_hook(args: argparse.Namespace) -> int:
    code, message = hook.claude(sys.stdin.read(), args.engine)
    if message:
        print(message, file=sys.stderr)
    return code


def _print_proof(repo: Path, engine: Engine, subject, proof, stamped: bool) -> None:
    if isinstance(proof, str):  # verifying this one failed before a proof could run
        print(f"✗ {subject.stem}\n    {proof}")
        return
    print(f"{'✓' if proof.passed else '✗'} {subject.id}")
    if proof.kind == FIXTURES_ONLY:
        print("    proof       the fixture (the mistake never reached git)")
    elif proof.kind == WORKTREE:
        print(f"    fix         uncommitted changes on top of {proof.vulnerable}")
    else:
        print(f"    fix         {proof.fixed}  {proof.subject}")
        print(f"    before      {proof.vulnerable}")
    if proof.fires_on:
        print(f"    fires on    {locations(proof.fires_on)}")
    for problem in proof.problems():
        print(f"    ✗ {problem}")
    if proof.passed and proof.survivors:
        print(
            f"    note        still matches after the fix at {locations(proof.survivors)}: "
            "a repeat the fix missed, or a false positive"
        )
    if proof.fixtures:
        print(f"    fixtures    {proof.fixtures} checked")
    print(f"    engine      {engine.label}")
    if stamped and proof.revisions.pin:
        print(f"    pinned      to {proof.fixed}, now that the fix is committed")
    if stamped:
        print(f"    stamped     {_rel(subject.path, repo)}")


def _proof_json(subject, proof, stamped: bool) -> dict:
    if isinstance(proof, str):
        return {"id": subject.stem, "passed": False, "error": proof}
    return {"id": subject.id, **proof.to_json(), "stamped": stamped}


def _finding_json(repo: Path, finding: Finding) -> dict:
    return {
        "rule": finding.rule_id,
        "path": finding.path,
        "line": finding.start_line,
        "end_line": finding.end_line,
        "code": _code(repo, finding, {}),
    }


def _targets(repo: Path, paths: list[str]) -> list[str] | None:
    if not paths:
        return None
    targets = []
    for p in paths:
        resolved = Path(p).resolve()
        if not resolved.is_relative_to(repo.resolve()):
            raise AntibodyError(f"{p} is outside {repo}")
        targets.append(os.path.relpath(resolved, repo.resolve()))
    return targets


def _within(path: str, targets: list[str] | None) -> bool:
    if targets is None:
        return True
    return any(t in (".", path) or PurePosixPath(path).is_relative_to(t) for t in targets)


def _code(repo: Path, finding: Finding, cache: dict[Path, list[str]]) -> str:
    path = repo / finding.path
    if path not in cache:
        try:
            cache[path] = path.read_text(errors="replace").splitlines()
        except OSError:
            cache[path] = []
    lines = cache[path]
    i = finding.start_line - 1
    return lines[i].strip() if 0 <= i < len(lines) else ""


def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _rel(path: Path, repo: Path) -> str:
    return str(path.relative_to(repo)) if path.is_relative_to(repo) else str(path)
