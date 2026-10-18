# Write a good antibody

An antibody is a Semgrep-format rule learned from one real fix. Your coding agent drafts
it, and `antibody verify` decides whether it's good enough to enforce. The agent skill in
`.agents/skills/antibody/SKILL.md` walks an agent through these steps.

## 1. Learn from the fix

| The fix is | Command | What `verify` proves |
|---|---|---|
| a commit | `antibody learn <commit>` | The rule fires near the change in the fix's parent, and never on lines the fix wrote. |
| uncommitted | `antibody learn --id <name>` | The same, comparing `HEAD` with your working tree. Once you commit, `verify` pins it to the commit. |
| not in git (the agent made the mistake and fixed it within one session) | `antibody learn --fixtures-only --id <name>` | Its fixture: every `ruleid:` line matches and every `ok:` line doesn't. |

`learn` writes a skeleton to `.antibodies/<id>.yml` and prints a brief with the diff.
Without arguments it uses your uncommitted changes, or `HEAD` if there are none.

## 2. Write the rule

Match only the known mistake first, then generalize one element at a time:

- **Wrong call or API:** match the call, and `pattern-not` the right form.
- **A check missing before a call:** `pattern-not-inside` for the check.
- **Untrusted input reaching a dangerous call:** `mode: taint`, with the fix's guard as a
  sanitizer.
- **A project convention:** match the raw form, and `pattern-not-inside` the one place
  allowed to use it. [The example below](#the-file-format) matches `$MODEL.query` on any
  model, except inside the `for_tenant()` helper.
- **Don't anchor on names that exist only in this diff**, unless the mistake really is
  specific to that API. Rules fitted that closely to one diff pass verification and then
  catch nothing.

The `message` is what the next agent reads when it repeats the mistake. Say what's wrong
and what to do instead.

## 3. Add a fixture

A file next to the rule, with the same name and a code extension, in Semgrep's
annotation style. For a fix that replaced `Invoice.query.all()` with
`for_tenant(Invoice, tenant_id).all()`, `.antibodies/unscoped-query.py` is:

```python
from app.db import for_tenant
from app.models import Invoice

# ruleid: unscoped-query
invoices = Invoice.query.all()
# ok: unscoped-query
invoices = for_tenant(Invoice, tenant_id).all()
```

Every match in the fixture must be annotated. Use `//` comments in JS and TS.

## 4. Verify, sweep, baseline

```bash
antibody verify <id>     # change the rule, not the fixture, until it passes
antibody sweep <id>      # every match in the code today
antibody baseline <id>   # accept the matches you're leaving, so only new ones fail
```

Tests and `.antibodies/` are left out of the proof. If the rule still matches something
after the fix, `verify` reports it as a possible repeat the fix missed.

## The file format

An antibody is a plain Semgrep rule with its history under `metadata.antibody`, so
`semgrep scan --config .antibodies --exclude .antibodies` works without antibody.

```yaml
rules:
  - id: unscoped-query
    message: >-
      Unscoped query: it can return other tenants' rows.
      Start from for_tenant(Model, tenant_id).
    severity: ERROR
    languages: [python]
    patterns:
      - pattern: $MODEL.query
      - pattern-not-inside: |
          def for_tenant(...):
              ...
    metadata:
      antibody:
        kind: convention                 # bug, security or convention
        source:
          commit: "882ae4a0860c6ad0f12ae4816260447b20f35b45"
          summary: "Scope invoice queries to the tenant"
        verified:                        # written by `antibody verify`
          engine: semgrep 1.181.0
          proof: commit                  # commit, worktree or fixtures
          vulnerable: 23c71b8f8a34
          fixed: 882ae4a0860c
          fires_on:
            - app/billing.py:10
          at: '2026-10-19'
```

## Engines

antibody runs your rules with Semgrep CE or [Opengrep](https://github.com/opengrep/opengrep).
The full test suite passes on Semgrep 1.181 and Opengrep 1.31.

- It uses the engine installed with it first (the `[semgrep]` extra), then Opengrep, then
  Semgrep from `PATH`.
- Pass `--engine`, or set `$ANTIBODY_ENGINE` to a name or a path, to choose one.
- Semgrep always runs with `--metrics=off`.
- Python and JavaScript/TypeScript are the first targets, but any language the engine
  supports works.
