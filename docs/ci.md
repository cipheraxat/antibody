# Run it in CI and pre-commit

Hooks catch an agent in the moment. CI and pre-commit catch everything else: edits from
tools without a hook, edits by people, and anything an agent was told to keep.

## Only new matches fail

There are three ways to decide what "new" means. Pick the one that fits where you run the
check:

| Command | New means | Good for |
|---|---|---|
| `antibody check` | not accepted in `.antibodies/baseline.json` | full scans |
| `antibody check --since origin/main` | not there at the ref, in files changed since it | pull requests |
| `antibody check --staged` | not in HEAD, in what's staged | pre-commit |

`antibody baseline` records today's matches, keyed by the matched code rather than line
numbers, so moving code doesn't make it new. A pasted copy of an accepted line still
counts as new. When accepted matches disappear, `check` tells you the baseline can
shrink.

## GitHub Actions

```yaml
# .github/workflows/antibody.yml (pin actions to commit SHAs in real use)
on: [pull_request]
jobs:
  antibody:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v10
      - run: uvx --from "antibody[semgrep]==0.3.0" antibody check --since "origin/$GITHUB_BASE_REF"
```

For GitHub code scanning, write SARIF with `antibody check --sarif antibody.sarif` and
upload it with `github/codeql-action/upload-sarif`.

## pre-commit

With the [pre-commit](https://pre-commit.com) framework:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/cipheraxat/antibody
    rev: v0.3.0
    hooks:
      - id: antibody
```

Without it, `antibody init --git-hook` writes `.git/hooks/pre-commit` running
`antibody check --staged`. It won't overwrite a hook you already have.

## Re-proving antibodies

`antibody verify --all` proves every antibody again against its fix. Commit proofs need
the fix commits in history, so use `fetch-depth: 0`.
