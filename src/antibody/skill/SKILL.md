---
name: antibody
description: Turn a fix into an antibody, a verified Semgrep rule that stops the same mistake coming back, enforced on every edit and in CI with no LLM. Use after fixing a bug, when the user corrects a mistake you could repeat, when given a fix commit or CVE to learn from, or when the antibody hook blocks one of your edits.
---

# Antibody: make a fix permanent

You write the rule; `antibody` proves it and enforces it. Never call an antibody done
until `antibody verify` passes.

## When to offer one

After you fix a bug, or when the user corrects something you did that could happen again
("don't use `datetime.utcnow()`", "always go through `tenant_query()`"), ask: *"Want me to
make this an antibody so it can't come back?"* Don't create one unasked.

## When the hook blocks your edit

`antibody: this edit repeats a mistake that was fixed before` means your last edit
introduced code that an antibody matches. The message says what to do instead and which
fix it was learned from (`git show <commit>` shows that fix). Fix the code. Add
`# nosemgrep` only if the user agrees the match is intentional.

## Making one

1. **Learn.** Pick where the fix lives:
   - committed: `antibody learn <commit>`
   - uncommitted changes: `antibody learn --id <name>`
   - nowhere in git (you wrote the mistake and fixed it in this session):
     `antibody learn --fixtures-only --id <name>`, then write the fixture from the
     conversation first.

   It writes `.antibodies/<id>.yml` and prints a brief with the diff. The file name and
   the rule id must match.
2. **Root cause.** One sentence: what went wrong, and what the fix does instead.
3. **Rule.** Replace `pattern: TODO`. Match only the known mistake first, then generalize
   one element at a time, re-verifying as you go.
   - Wrong call or API: match the call, and `pattern-not` the right form.
   - Missing check before a call: `pattern-not-inside` for the check.
   - Untrusted input reaching a dangerous call: `mode: taint`, with the fix's guard
     under `pattern-sanitizers`.
   - Don't anchor on names that exist only in this diff unless the mistake is specific to
     that API. Overfit rules pass verification and then catch nothing.
4. **Message and kind.** `message` is what the next agent reads when it repeats the
   mistake: what's wrong and what to do instead, in one or two sentences. Set `kind` to
   bug, security or convention, and add `cwe` for security.
5. **Fixture.** `.antibodies/<id>.<ext>`: the mistake under a `# ruleid: <id>` line and
   the fixed form under `# ok: <id>` (`//` comments in JS/TS). Every match in it must be
   annotated.
6. **Verify.** `antibody verify <id>` passes only if the rule fires on the mistake near the
   change, never fires on lines the fix wrote, and the fixture holds. A fixtures-only
   antibody needs both `ruleid` and `ok` lines. Change the rule, not the fixture. If it
   can't pass after a few honest attempts, stop and explain why.
7. **Sweep and baseline.** `antibody sweep <id>` lists every match in the code today.
   Fix the real repeats if the user wants, then `antibody baseline <id>` to accept the rest
   on purpose, so only new matches fail.
8. **Hand off.** Report what it catches, the verify result and the repeats found. Leave
   committing to the user.

## Commands

| Command | What it does |
|---|---|
| `antibody learn [commit] [--id ID] [--fixtures-only]` | Skeleton plus brief for a fix |
| `antibody verify <id>` | The proof; records it in the file on success |
| `antibody sweep <id> [paths]` | Every match in the current code |
| `antibody baseline [ids]` | Accept today's matches so only new ones fail |
| `antibody check [--since REF]` | New matches from verified antibodies; exit 1 if any (CI) |
| `antibody list` | What's in `.antibodies/` and how each was proven |

Add `--json` to verify, sweep, check and list for machine-readable output, and
`--repo <path>` to work against another clone.
