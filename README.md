# antibody

**Every bug you fix, and every mistake you correct your coding agent on, becomes a verified
rule that stops it coming back.**

Agents repeat mistakes. So do teams. A note in `CLAUDE.md` is a suggestion, and the
lesson from a fix is usually gone the moment it merges. `antibody` keeps it. Your coding
agent drafts a [Semgrep](https://semgrep.dev)-format rule from the fix. `antibody` *proves*
the rule fires on the mistake and stays silent on the fix. It then enforces the rule on
every file the agent edits and in CI, with no LLM, no network and no tokens. Only new
matches count, so turning it on never breaks a build.

The LLM writes the check once. A deterministic tool runs it from then on.

## What it looks like

A fix made timestamps timezone-aware. Later, Claude Code writes `datetime.utcnow()` in
another file, and the edit hook answers right away:

```
antibody: this edit repeats a mistake that was fixed before
  app/invoices.py:5  [naive-datetime]  This makes a timestamp with no timezone, which breaks comparisons and shifts times across servers. Use datetime.now(timezone.utc).
    learned from 95ffe5603abe "Use timezone-aware timestamps in billing"
Fix the code. Ask the user before suppressing it with `# nosemgrep`.
```

Claude Code shows that message to Claude, which fixes the code before moving on. An old
`datetime.now()` elsewhere in the repo was accepted in the baseline, so it doesn't block
anyone.

## Quick start

```bash
# Not on PyPI yet: install from GitHub. The [semgrep] extra brings the engine along.
uv tool install "antibody[semgrep] @ git+https://github.com/cipheraxat/antibody"

cd your-repo
antibody init --agent claude   # .antibodies/, the agent skill, and the edit hook in .claude/settings.json
```

Then, after a fix, ask your agent to *"make an antibody from that fix"*. The skill walks
it through these steps, which you can also run yourself:

```bash
antibody learn                 # learns from uncommitted changes if there are any, else HEAD
antibody verify <id>           # the proof; iterate on the rule until it passes
antibody sweep <id>            # every match today: fix the real repeats...
antibody baseline <id>         # ...and accept the rest, so only new matches fail
```

## Three ways to learn

| The fix is | Command | What `verify` proves |
|---|---|---|
| a commit | `antibody learn <commit>` | Fires near the change in the fix's parent, and never on lines the fix wrote |
| uncommitted | `antibody learn --id <name>` | The same, `HEAD` against your working tree. After you commit, `verify` pins it to the commit automatically |
| not in git (the agent made the mistake and fixed it in one session) | `antibody learn --fixtures-only --id <name>` | The fixture: every `ruleid:` line matches, every `ok:` line doesn't |

Tests and `.antibodies/` are left out of the proof. Matches the fix left in place are
reported as possible repeats.

## Only new matches fail

- **The edit hook** compares the edited file with `HEAD`. It blocks only mistakes the
  agent just introduced, never old code it happened to touch.
- **`antibody baseline`** records today's accepted matches in `.antibodies/baseline.json`,
  keyed by the matched code rather than line numbers. `antibody check` then fails only on
  matches beyond it. A pasted copy of an accepted line still counts as new.
- **`antibody check --since origin/main`** looks only at files changed since a ref. That
  suits pull requests.

```yaml
# .github/workflows/antibody.yml (pin actions to commit SHAs in real use)
on: [pull_request]
jobs:
  antibody:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: astral-sh/setup-uv@v6
      - run: uvx --from "antibody[semgrep] @ git+https://github.com/cipheraxat/antibody" antibody check --since origin/${{ github.base_ref }}
```

## The hook

`antibody init --agent claude` adds this to `.claude/settings.json`, keeping any hooks
already there:

```json
{"hooks": {"PostToolUse": [{"matcher": "Edit|Write", "hooks": [
  {"type": "command", "command": "antibody", "args": ["hook", "claude"], "timeout": 60,
   "statusMessage": "antibody: checking edit"}]}]}}
```

It takes about **0.5 s** on a file an antibody covers and **0.25 s** on anything else,
measured on an M-series Mac with Semgrep 1.181. It exits 2 with the message above on a new
match, which Claude Code shows to Claude. It exits 0 when clean, and 1 if something is
broken, so a broken hook never blocks your work.

## A security example: setuptools CVE-2024-6345

setuptools formatted package URLs into `os.system` command strings. From the fix
[`88807c7`](https://github.com/pypa/setuptools/commit/88807c7062788254f654ea8c03427adc859321f0),
an agent wrote [`examples/os-system-formatted-command.yml`](examples/os-system-formatted-command.yml).
`antibody verify` confirmed that it catches all four vulnerable calls and none of the
fixed code. The sweep found no other instances in setuptools. The rule doesn't mention
setuptools, so it works on any Python codebase.

## Commands

| Command | What it does |
|---|---|
| `antibody init [--agent claude] [--skill]` | Create `.antibodies/`, plus the skill and edit hook |
| `antibody learn [commit] [--id ID] [--fixtures-only]` | Write a skeleton and print a brief for the agent |
| `antibody verify <id>... \| --all` | Prove each antibody; `--fix COMMIT` records the fix, `--no-stamp` leaves files alone |
| `antibody sweep <id> [paths]` | List every match of one antibody |
| `antibody baseline [ids]` | Accept today's matches |
| `antibody check [paths] [--since REF] [--no-baseline] [--sarif FILE]` | New matches from verified antibodies; exit 1 if any |
| `antibody list` | Antibodies, how each was proven, and their kind |
| `antibody hook claude` | The edit hook (reads Claude Code's event on stdin) |

All but `hook` take `--repo PATH`. `verify`, `sweep`, `check` and `list` take `--json`.

## The file format

An antibody is a plain Semgrep rule with its history under `metadata.antibody`, so
`semgrep scan --config .antibodies --exclude .antibodies` works without antibody.

```yaml
rules:
  - id: naive-datetime
    message: >-
      This makes a timestamp with no timezone ... Use datetime.now(timezone.utc).
    severity: ERROR
    languages: [python]
    pattern-either:
      - pattern: datetime.datetime.utcnow()
      - pattern: datetime.datetime.now()
    metadata:
      antibody:
        kind: bug                        # bug, security or convention
        source:
          commit: "95ffe5603abe..."
          summary: "Use timezone-aware timestamps in billing"
        verified:                        # written by `antibody verify`
          engine: semgrep 1.181.0
          proof: commit
          vulnerable: 8d7f55689db5
          fixed: 95ffe5603abe
          fires_on:
            - app/billing.py:5
          at: '2026-10-18'
```

A file next to it with the same name and a code extension (`naive-datetime.py`) is its
fixture, in Semgrep's annotation style:

```python
# ruleid: naive-datetime
issued = datetime.utcnow()
# ok: naive-datetime
issued = datetime.now(timezone.utc)
```

## Engine

Antibody runs [Opengrep](https://github.com/opengrep/opengrep) if it's on `PATH`.
Otherwise it uses Semgrep CE, through its fast OCaml CLI, always with `--metrics=off`.
Pass `--engine` or set `$ANTIBODY_ENGINE` to choose. Python and JavaScript/TypeScript are
the first targets, and any language the engine supports works.

## Status

v0.2. Next:

- a Claude Code plugin bundling the skill and hook (after a PyPI release)
- blocking a bad edit *before* it's written (PreToolUse), and hooks for Cursor, Codex and opencode
- `learn --auto` with the Claude API, for pull-request bots
- snapshotting agent edits, so corrections are proven against real code rather than fixtures

## Development

```bash
uv sync
uv run pytest      # runs against real git repos and the real engine (~30 s)
```

## License

[MIT](LICENSE)
