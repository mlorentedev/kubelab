---
id: lesson-416-a-guard-the-guard-must-assert-on-the-derived-artifact
type: lesson
status: active
created: "2026-09-02"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, testing, mutation-testing, vacuous-tests]
---

# An anti-vacuity test must assert on the value under test, not one step upstream of it

**Context**: Three guards written in this repository on the same day were found to pass while the
property they protect was unenforceable (#1546, #1557, #1565). Two of them **already carried an
anti-vacuity test**, and both of those tests passed.

**Problem**: The pattern is always the same. A guard compares a *derived* set against an expectation:

```python
exposed = {name: port for name, spec in ports.items() if spec["expose"]["default"] is True}
assert set(exposed.values()) <= allowed_by_ufw          # vacuous when `exposed` is empty
```

`ports` renders three entries, so the file's guard-the-guard —
`assert {"web", "websecure", "traefik"} <= set(ports)` — is green. But none of the three *states*
`expose.default` (two inherit the chart's default, one sets it `false`), so `exposed` is `{}` and the
comparison is trivially satisfied. Removing `443/tcp` from the allow-list, a port Traefik
unquestionably publishes, left the suite green.

The anti-vacuity test verified that the **raw input** was populated. What was empty was the value
**one derivation later** — the one the assertion actually consumes.

I then found the identical shape in guards I had written that same afternoon, in the file whose entire
thesis is that a check comparing a hand-written expectation against something that happens to match it
proves nothing. Setting `ADMIN_METHODS = ()` made `REQUIRED_ADMIN_SCOPES` the empty set, so
`REQUIRED - granted` was empty, so **all eight scope tests passed** — the whole apparatus switches off
by emptying one tuple. An empty expectation is not a weak expectation; it matches everything, which is
the strongest form of the failure the file was written to prevent.

**Solution**: Assert on the artefact the guard consumes, and prove it by mutation:

```python
assert ADMIN_METHODS, "empty means every scope check passes against any grant whatsoever"
assert REQUIRED_ADMIN_SCOPES, "empty means the grant check cannot fail"
missing = LOAD_BEARING_ADMIN_METHODS - set(ADMIN_METHODS)   # a FLOOR, not a copy
```

The floor is deliberately a small anchor rather than a restatement of the full tuple: copying it back
would reintroduce the second declaration the guard exists to remove, and would fail on legitimate
widening. Re-run the mutation afterwards — `ADMIN_METHODS = ()` now fails.

**Rule**: **A guard-the-guard belongs on the last value before the assertion, never on an input to
it.** "Is the render populated" and "is the derived set populated" are different questions, and only
the second one protects anything. The cheap way to find out which you wrote is to **empty the derived
value and re-run**: any test that survives was never testing. Do this for every filtering,
comprehension, or `is True` selection between the source data and the assertion — each one is a place
where a set can silently become empty while everything upstream stays healthy.

**Tags**: `#testing` `#mutation-testing` `#vacuous-tests` `#issue-1565` `#pr-1563`
