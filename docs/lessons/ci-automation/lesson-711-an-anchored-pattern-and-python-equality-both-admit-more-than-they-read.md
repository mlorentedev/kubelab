---
id: lesson-711-an-anchored-pattern-and-python-equality-both-admit-more-than-they-read
type: lesson
status: active
created: "2026-11-04"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, deploy-merge, python]
---

# An anchored pattern under `match` and Python's `==` both admit more than they appear to

**Context**: `toolkit/features/deploy_shape.py` decides which staging deploy PRs merge without a human
(DELIVERY-004, #1619). It walks the YAML of both sides and compares every leaf, and it checks the new tag
against `tag_pattern`, `^sha-[0-9a-f]{7,40}$`. The second review (#3062 F5) found two gaps.

**Problem**: leaves were compared with `==`. In Python `False == 0 == 0.0` and `True == 1`, so a values
file where `enable_blog: false` became `enable_blog: 0` reported no change, and that diff rode along
with a mechanical deploy. Separately, the code used `fullmatch`, and no test failed when it became
`match`. The pattern is anchored, which makes the two look equivalent, but `$` also matches just before
a final newline: `re.match(r"^sha-[0-9a-f]{7}$", "sha-0ddba11\n")` matches, and a quoted YAML scalar can
carry that newline.

**Solution**: `_leaves` compares `(type(x), x)`, so a type change is a change. Three tests pin the
behaviour, and each goes red under its own mutation (`make mutate`):

- `false` -> `0` and `false` -> `0.0` are refused;
- a tag ending in `\n`, written consistently to the values file and the overlay, is refused;
- a resolved commit sha one character too long is refused.

**Rule**: when a comparison decides what is allowed in, compare type as well as value. Use `fullmatch`
and pin it with an input that only `fullmatch` refuses. The anchors in the pattern are not that pin,
because `$` admits a trailing newline.

**Tags**: `#deploy-merge` `#python` `#issue-3062`
