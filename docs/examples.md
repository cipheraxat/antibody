# Examples

## A mistake agents keep making: naive timestamps

A fix in `app/billing.py` replaced `datetime.utcnow()` with `datetime.now(timezone.utc)`.
The agent learned an antibody from it:

```text
$ antibody verify naive-datetime
✓ naive-datetime
    fix         95ffe5603abe  Use timezone-aware timestamps in billing
    before      8d7f55689db5
    fires on    app/billing.py:5
    fixtures    1 checked
    engine      semgrep 1.181.0
    stamped     .antibodies/naive-datetime.yml

$ antibody sweep naive-datetime
naive-datetime: 1 match
  app/reports.py:5  report["generated_at"] = datetime.now()

$ antibody baseline
accepted 1 match from 1 antibody in .antibodies/baseline.json
```

Later the agent wrote `datetime.utcnow()` in a new file, and the edit hook answered right
away:

```text
antibody: this edit repeats a mistake that was fixed before
  app/invoices.py:5  [naive-datetime]  This makes a timestamp with no timezone, which breaks
  comparisons and shifts times across servers. Use datetime.now(timezone.utc).
    learned from 95ffe5603abe "Use timezone-aware timestamps in billing"
Fix the code. Ask the user before suppressing a match with `# nosemgrep`.
```

The old `datetime.now()` in `reports.py` is in the baseline, so it never blocks anyone.

## A live Claude Code session

This was run in Claude Code 2.1.300 with Sonnet, in a repo set up as above:

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
