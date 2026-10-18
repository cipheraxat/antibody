# Examples

## A convention no linter knows: tenant-scoped queries

In a multi-tenant billing app, every query must start from `for_tenant(Model, tenant_id)`
in `app/db.py`, so a customer only ever sees their own rows. No linter ships with that
rule. A fix in `app/billing.py` replaced `Invoice.query.all()` with
`for_tenant(Invoice, tenant_id).all()`, and the agent learned an antibody from it. The
rule matches `.query` on any model, and leaves out the helper itself:

```yaml
patterns:
  - pattern: $MODEL.query
  - pattern-not-inside: |
      def for_tenant(...):
          ...
```

```text
$ antibody verify unscoped-query
✓ unscoped-query
    fix         882ae4a0860c  Scope invoice queries to the tenant
    before      23c71b8f8a34
    fires on    app/billing.py:10
    fixtures    1 checked
    engine      semgrep 1.181.0
    stamped     .antibodies/unscoped-query.yml
next: antibody sweep unscoped-query

$ antibody sweep unscoped-query
unscoped-query: 1 match
  app/admin.py:5  return Invoice.query.count()  # every tenant, on purpose
Fix the real repeats; accept the rest with `antibody baseline unscoped-query` so only new matches fail.

$ antibody baseline unscoped-query
accepted 1 match from 1 antibody in .antibodies/baseline.json
```

The count in `admin.py` covers every tenant on purpose, so it's in the baseline and never
blocks anyone.

Later the agent added `unpaid_total()` to `app/invoices.py`, starting from `Invoice.query`
again, and the edit hook answered right away:

```text
antibody: this edit repeats a mistake that was fixed before
  app/invoices.py:9  [unscoped-query]  Unscoped query: it can return other tenants' rows.
  Start from for_tenant(Model, tenant_id).
    learned from 882ae4a0860c "Scope invoice queries to the tenant"
Fix the code. Ask the user before suppressing a match with `# nosemgrep`.
```

For agents without an edit hook, the pre-commit hook and `antibody check` catch the same
line:

```text
$ git commit -m "Sum unpaid invoices" app/invoices.py
app/invoices.py:9  [unscoped-query]  unpaid = Invoice.query.filter_by(paid=False)
✗ 1 new match from 1 antibody

$ antibody check --since HEAD
app/invoices.py:9  [unscoped-query]  unpaid = Invoice.query.filter_by(paid=False)
✗ 1 new match from 1 antibody
```

The whole rule file and its fixture are in [Write a good antibody](writing-antibodies.md).

## A live Claude Code session

This test used an earlier antibody, `naive-datetime`, learned from a fix that replaced
`datetime.utcnow()` with `datetime.now(timezone.utc)`. It ran in Claude Code 2.1.300 with
Sonnet:

- **Told to use `datetime.utcnow()` anyway**, "because our serializer expects naive UTC",
  Claude made the edit and the hook blocked it. Claude named the rule, the line and the
  source commit. It didn't override the user, and asked whether to keep `utcnow()` with
  `# nosemgrep: naive-datetime` or switch to `datetime.now(timezone.utc)`.
- **Given the same task without the insistence**, Claude read the antibody's commit and
  wrote the timezone-aware version from the start. Committed antibodies guide an agent
  even before a hook fires.

## A security fix: setuptools CVE-2024-6345

setuptools formatted package URLs into `os.system` command strings. From the fix
[`88807c7`](https://github.com/pypa/setuptools/commit/88807c7062788254f654ea8c03427adc859321f0),
an agent wrote [`examples/os-system-formatted-command.yml`](../examples/os-system-formatted-command.yml):

```text
$ antibody verify os-system-formatted-command
✓ os-system-formatted-command
    fix         88807c706278  Modernize package_index VCS handling
    before      4a0a9ce58751
    fires on    setuptools/package_index.py:888, setuptools/package_index.py:892, setuptools/package_index.py:907, setuptools/package_index.py:911
    fixtures    1 checked
```

It catches all four vulnerable calls and none of the fixed code. The sweep found no other
instances, so the fix was complete. The rule doesn't mention setuptools, so it works on
any Python codebase.
