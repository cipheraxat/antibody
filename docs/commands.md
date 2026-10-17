# Commands

| Command | What it does |
|---|---|
| `antibody init [--agent NAMES] [--git-hook]` | Set up `.antibodies/`, AGENTS.md, the agent skill, and hooks for your coding agents |
| `antibody learn [commit] [--id ID] [--fixtures-only]` | Write a skeleton antibody and print a brief for the agent |
| `antibody verify <id>... \| --all` | Prove each antibody fires on the mistake and not on the fix |
| `antibody sweep <id> [paths]` | List every match of one antibody in the code today |
| `antibody baseline [ids]` | Accept today's matches, so only new ones fail |
| `antibody check [paths] [--since REF \| --staged]` | Report new matches from verified antibodies; exit 1 if there are any |
| `antibody list` | Show antibodies, how each was proven, and their kind |
| `antibody hook <agent>` | Run as a coding agent's hook; reads the tool's event on stdin |

All commands except `hook` take `--repo PATH`. `verify`, `sweep`, `check` and `list` take
`--json`. `verify`, `sweep`, `baseline`, `check` and `hook` take `--engine` (a name or a
path).

## init

- `--agent NAMES`: comma-separated, from `claude`, `codex`, `gemini`, `cursor` and
  `copilot`, or `all`. Without it, `init` sets up the agents the repo already uses: it
  looks for `.claude/` or CLAUDE.md, `.codex/`, `.gemini/` or GEMINI.md, `.cursor/` or
  `.cursorrules`, and `.github/copilot-instructions.md` or `.github/hooks/`.
- `--git-hook`: add `.git/hooks/pre-commit` running `antibody check --staged`. It isn't
  added if a pre-commit hook already exists.

## learn

- `commit`: the fix. By default, uncommitted changes if there are any, else `HEAD`.
- `--id`: the antibody's name. For commits, the default comes from the commit subject.
- `--fixtures-only`: the mistake never reached git, so the fixture alone proves the rule.

## verify

- `--all`: verify every antibody in `.antibodies/`.
- `--fix COMMIT`: record `COMMIT` as the fix to prove against.
- `--window N`: the most lines a match can be from the change and still count (default 25).
- `--no-stamp`: don't write the proof into the rule file.

## check

- `--since REF`: only files changed since `REF`, and only matches that weren't there at `REF`.
- `--staged`: only what's staged, compared with `HEAD`.
- `--no-baseline`: count accepted matches as new too.
- `--include-unverified`: also run antibodies that haven't passed `verify`.
- `--sarif FILE`: also write SARIF, for GitHub code scanning. It can't be combined with
  `--since` or `--staged`.

## hook

`antibody hook claude|codex|gemini|cursor|copilot` speaks each tool's hook protocol. You
rarely run it yourself, because `antibody init` wires it up. See [agents.md](agents.md).
