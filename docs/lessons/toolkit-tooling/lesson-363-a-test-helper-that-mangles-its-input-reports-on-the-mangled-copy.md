---
id: lesson-363-a-test-helper-that-mangles-its-input-reports-on-the-mangled-copy
type: lesson
status: active
created: "2026-08-21"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, testing, terraform, secrets]
---

# A test helper that mangles its input makes every guard downstream report on the mangled copy

**Context**: Adding a drift guard to `tests/test_gcp_hub_module.py` so that
`spoke_servers` — a Terraform variable holding literal Tailscale apiserver URLs
— could not silently disagree with the `common.yaml` derivation it claims to
mirror. The guard derives the expected URLs and compares.

**Problem**: It failed, and the failure message named the wrong culprit:

```
AssertionError: spoke_servers defaults to ['https:\n    prod    = '] but
common.yaml derives ['https://100.64.0.11:6443', 'https://100.64.0.2:6443']
```

Not a drift. The module was correct. The *reader* was broken. Every assertion in
that file runs against `_tf_text()`, which concatenated the `.tf` files and
stripped comments with two regexes:

```python
text = re.sub(r"#[^\n]*", "", text)
text = re.sub(r"//[^\n]*", "", text)
```

HCL line comments do open with `#` and `//`. So does the middle of every URL.
`"https://100.64.0.11:6443"` was truncated to `"https:` before any test saw it,
and a `#` inside any string took the rest of its line with it.

The consequence is not cosmetic, and this is the part worth carrying.
`TestNoCredentialLiterals` — the guard whose entire job is to prove no
credential was pasted into a public repository's `.tf` files — scans that same
text. A credential embedded the way credentials usually are, `https://user:token@host`,
was cut away *before* the scan. The guard reported clean having examined a
string that no longer contained the thing it hunts for. It had been green for
its whole life and would have stayed green through the leak it exists to catch.

**Solution**: Replaced both regexes with one left-to-right pass that tracks
quote state, since neither `#` nor `//` opens a comment inside a double-quoted
string, and honoured backslash escapes so a `\"` does not end one. Then guarded
the helper itself — including a **positive control** that its original purpose
still holds, so a future "simplification" back to the regex form cannot pass by
deleting the capability along with the bug:

```python
def test_a_url_keeps_its_double_slash(self) -> None:
    assert _strip_comments('a = "https://host:6443"') == 'a = "https://host:6443"'

def test_a_real_line_comment_is_still_removed(self) -> None:
    assert "spot" not in _strip_comments("# provisioning_model = SPOT\nx = 1").lower()
```

Reverting the helper to its regex form produced four failures, two of them in
guards that had nothing to do with comments.

**Rule**: **A shared test helper that transforms its input is load-bearing
security code when any guard downstream searches that input for something.** Two
practices follow:

- **Guard the helper, both directions.** Assert what it must remove *and* what
  it must preserve. A test that only checks removal passes for a helper that
  removes everything.
- **Be suspicious of a green scanner you have never seen go red.** The failure
  mode here is silent by construction: the scan succeeds, finds nothing, and
  reports the absence honestly — of a string that was deleted upstream. This is
  the same shape as `review-attestation` asking whether a review was *published*
  rather than whether a known error appeared: verify the capability, not the
  absence of a symptom.

The defect surfaced only because a *new* guard happened to assert on a value
containing `//`. Nothing else in the file did. A regex over a structured format
is a parser with the hard cases deleted, and the hard case is usually the one
carrying the secret.

**Tags**: `#testing` `#terraform` `#secrets` `#ssot` `#pr-1217`
