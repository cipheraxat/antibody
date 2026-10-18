<p align="center">
  <img src="docs/assets/logo.svg" width="120" alt="antibody logo">
</p>

<h1 align="center">antibody</h1>

<p align="center">
  <b>Every fix becomes a rule your AI coding agent can't break.</b>
</p>

<p align="center">
  <a href="https://pypi.org/project/antibody/"><img src="https://img.shields.io/pypi/v/antibody" alt="PyPI"></a>
  <a href="https://pypi.org/project/antibody/"><img src="https://img.shields.io/pypi/pyversions/antibody" alt="Python versions"></a>
  <a href="https://github.com/cipheraxat/antibody/actions/workflows/ci.yml"><img src="https://github.com/cipheraxat/antibody/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#supported-tools">Supported tools</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#documentation">Docs</a> ·
  <a href="docs/examples.md">Examples</a>
</p>

https://github.com/user-attachments/assets/5b0fc63c-52ac-4e35-889b-e1fa8cfdeecb

---

AI coding agents repeat mistakes, and a line in `AGENTS.md` is only a suggestion.
**antibody** turns each fix into a small rule, proves it against the real fix, and checks
every edit your agent makes, with no LLM in the loop.

```text
antibody: this edit repeats a mistake that was fixed before
  app/invoices.py:9  [unscoped-query]  Unscoped query: it can return other tenants' rows.
  Start from for_tenant(Model, tenant_id).
    learned from 882ae4a0860c "Scope invoice queries to the tenant"
Fix the code. Ask the user before suppressing a match with `# nosemgrep`.
```

<sub>What the agent sees right after it writes <code>Invoice.query</code> again. Here every query must
go through the app's own <code>for_tenant()</code>, a rule no linter ships with.</sub>

## Why antibody

- **Lessons that stick.** Agents forget between sessions, and rules in prompt files are
  only suggestions. An antibody is a deterministic check that runs on every edit.
- **Proven, not guessed.** Your agent drafts a Semgrep-format rule from the fix.
  `antibody verify` only accepts it if it fires on the old code and stays silent on the fix.
- **No noise.** Only new matches count, so old code never blocks an edit or breaks a build.
- **Any tool.** It works with Claude Code, Codex, Gemini CLI, Cursor, GitHub Copilot, any
  agent that reads AGENTS.md, git hooks and CI.

## Install

```bash
uv tool install "antibody[semgrep]"     # or: pipx install "antibody[semgrep]"
```

The `[semgrep]` extra brings the rule engine. If you already use
[Opengrep](https://github.com/opengrep/opengrep), plain `antibody` is enough.

## Quick start

```bash
cd your-repo
antibody init          # .antibodies/, AGENTS.md, the agent skill, and hooks for the agents it finds
```

Fix a bug as usual, then ask your agent to *"make an antibody from that fix."* It runs:

```bash
antibody learn         # brief + skeleton from the fix (uncommitted changes, or HEAD)
antibody verify <id>   # the proof: fires on the mistake, silent on the fix
antibody sweep <id>    # every repeat in the code today
antibody baseline <id> # accept what's left, so only new matches fail
```

## Supported tools

| Tool | How antibody plugs in | Catches a repeat |
|---|---|---|
| **Claude Code** ✓ | skill + `PostToolUse` hook | right after the edit |
| **OpenAI Codex** | skill + `PostToolUse` hook | right after the edit |
| **Gemini CLI** | skill + `AfterTool` hook | right after the edit |
| **Cursor** | skill + `stop` hook | before the agent ends its turn |
| **GitHub Copilot** (CLI and cloud agent) | skill + `agentStop` hook | before the agent ends its turn |
| **Windsurf, Cline, opencode, Amp, Zed, Aider, …** | AGENTS.md + skill + pre-commit hook | at commit |
| **Any CI** | `antibody check --since origin/main` | on every pull request |

`antibody init` sets up the tools it detects. Choose them yourself with
`--agent claude,cursor` or `--agent all`. ✓ means tested in a live session; the others are
tested against each tool's documented hook format. See [docs/agents.md](docs/agents.md).

## How it works

```text
  fix ─► antibody learn ─► agent writes the rule ─► antibody verify ─► checked on every edit,
                                                    fires on the bug,   commit and pull request
                                                    silent on the fix
```

1. **Learn** from a commit, from uncommitted changes, or, for a mistake that never reached
   git, from a fixture.
2. **Prove.** The rule must fire near the change in the old code and never on lines the
   fix wrote.
3. **Enforce.** Hooks, pre-commit and CI run the rules with Semgrep or Opengrep. That's
   about 0.5 s per edit, with no network and no tokens.

Antibodies are plain Semgrep rules in `.antibodies/`, so they work without antibody too.

## Documentation

| Goal | Start here |
|---|---|
| Set up your coding agent | [docs/agents.md](docs/agents.md) |
| Write a good antibody | [docs/writing-antibodies.md](docs/writing-antibodies.md) |
| Run it in CI or pre-commit | [docs/ci.md](docs/ci.md) |
| Look up a command | [docs/commands.md](docs/commands.md) |
| See real examples, including a CVE | [docs/examples.md](docs/examples.md) |

## Contributing

Issues and pull requests are welcome.

```bash
git clone https://github.com/cipheraxat/antibody && cd antibody
uv sync && uv run pytest     # runs against real git repos and the real engine
```

## License

[MIT](LICENSE)
