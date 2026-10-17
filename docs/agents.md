# Set up your coding agent

`antibody init` gives every agent what it needs. It always writes the parts any agent
can use, then adds a hook for each agent it finds in the repo, or for the ones you name.

```bash
antibody init                         # agents detected from .claude/, .codex/, .gemini/, .cursor/, .github/
antibody init --agent claude,cursor   # pick them yourself
antibody init --agent all
antibody init --git-hook              # also add a pre-commit hook
```

Running it again is safe. It never duplicates a hook, and it keeps every setting and hook
that was already there.

## What every agent gets

| File | What it's for |
|---|---|
| `.antibodies/` | The rules, their fixtures, and `baseline.json`. |
| `.agents/skills/antibody/SKILL.md` | The [Agent Skill](https://agentskills.io) that teaches an agent to learn, verify and respect antibodies. Read by Codex, Cursor, GitHub Copilot, Gemini CLI and opencode. |
| `AGENTS.md` | A short marked section telling any agent to run `antibody check --since HEAD` after editing code, and to offer an antibody after a fix. `init` refreshes it in place. |

## Hooks for each tool

### Claude Code

- Writes a `PostToolUse` hook to `.claude/settings.json` (matcher `Edit|Write`), and the
  skill to `.claude/skills/antibody/`.
- Checks right after each edit. Exit code 2 puts the message in front of Claude.
- Tested live: see [examples](examples.md#a-live-claude-code-session).

### OpenAI Codex

- Writes a `PostToolUse` hook to `.codex/hooks.json` (matcher `apply_patch|Edit|Write`).
  Antibody reads the edited files from the patch.
- Adds the message to the edit's result (`additionalContext`).
- Codex runs project hooks only after you trust them: run `/hooks` in Codex.

### Gemini CLI

- Writes an `AfterTool` hook to `.gemini/settings.json` (matcher `write_file|replace`).
- Adds the message to the tool's result (`additionalContext`).
- Gemini CLI asks before it runs a new project hook for the first time.

### Cursor

- Writes a `stop` hook to `.cursor/hooks.json`, with `loop_limit: 2`.
- When the agent finishes a turn, antibody checks every file changed since HEAD. If the
  agent added a match, antibody replies with a follow-up message so the agent fixes it.
  After two follow-ups it lets the agent stop.
- Project hooks run in trusted workspaces.

### GitHub Copilot

- Writes an `agentStop` hook to `.github/hooks/antibody.json`, which Copilot CLI and the
  Copilot cloud agent both read.
- At the end of a turn, a new match blocks the stop once, with the message as the reason.

### Windsurf, Cline, opencode, Amp, Zed, Jules and others

These read AGENTS.md, and many also read `.agents/skills/`, so they know to run
`antibody check --since HEAD` after editing. Add the pre-commit hook so nothing slips
through: `antibody init --git-hook`.

### Aider

```bash
aider --lint-cmd "antibody check --since HEAD" --auto-lint
```

## How the hooks decide

- A match counts only if it's new: it isn't in HEAD's version of the file, and it isn't
  accepted in `.antibodies/baseline.json`. Old code never blocks the agent.
- Edit hooks check the file that was just edited. End-of-turn hooks check every file
  changed since HEAD, untracked files included, so they also catch edits made with shell
  commands.
- Test files and `.antibodies/` are skipped.
- If antibody itself fails (no engine, a broken rule file), the hook fails open. It never
  blocks the agent, and you see a warning.
- Hooks run `antibody` from your PATH, so install it with
  `uv tool install "antibody[semgrep]"`.

## Speed

On an M-series Mac, an edit to a file an antibody covers takes about **0.5 s** with
Semgrep 1.181 and **1.4 s** with Opengrep 1.31. Any other file takes about **0.25 s**,
because the engine never starts.
