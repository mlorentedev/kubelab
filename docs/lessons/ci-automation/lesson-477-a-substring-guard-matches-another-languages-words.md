---
id: lesson-477-a-substring-guard-matches-another-languages-words
type: lesson
status: active
created: "2026-09-28"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, guards, regex, retirement]
---

# A substring guard matches another language's words, and a word boundary misses identifiers

**Context**: OPS-023's AC5 guard, `tests/test_no_live_minio_references.py`,
fails when any live file names the retired object store. PR 3b swept the docs
until the guard turned green.

**Problem**: The guard matched `minio` as a case-insensitive substring. After
every real reference was gone, two docs still failed. They contain the Spanish
`dominio` / `dominios` ("domain"), which carries `minio` inside it. The first
fix that comes to mind is `\bminio\b`, and it is wrong in the other direction:
`_` is a word character, so `\b` does not fire inside `beelink_minio_dir` or
`MINIO_ROOT_USER`. Those are exactly the identifiers a retirement guard exists
to catch.

**Solution**: Guard on "not preceded by a letter":

```python
PATTERN = re.compile(r"(?<![a-z])minio", re.IGNORECASE)
```

It rejects `dominio` and accepts `beelink_minio_dir`, `quay.io/minio/minio`
and `MinIO S3`. Each of those cases is a parametrized test, so a later
"simplification" to `\b` or back to a substring fails on the case it would
break.

**Rule**: A name guard needs positive and negative cases, taken from the
corpus it scans, before its regex is trusted. Take them from every language
that appears in that corpus, and from every identifier style: `snake_case`,
`SCREAMING_CASE` and path segments. The boundary you want is usually "not
inside a longer word", not "`\b`". `\b` treats `_` and digits as part of the
word, so it hides exactly the identifiers.

**Tags**: `#guards` `#regex` `#ops-023` `#issue-972`
