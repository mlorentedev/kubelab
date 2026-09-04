---
id: lesson-420-a-try-around-a-yield-catches-the-callers-failures
type: lesson
status: active
created: "2026-09-02"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, python, contextmanager, error-handling, observability]
---

# A `try` that spans a `yield` catches the *caller's* failures and reports them as its own

**Context**: `toolkit obs triage` was fixed (#1534, #1595) so it could no longer
report a verdict of health from a Loki it never reached. The fix gave
`_loki_client` and `_grafana_client` a `@contextmanager` shape: open a
`kubectl port-forward`, yield a client, wrap any transport failure in
`LogsUnavailableError` / `AlertsUnavailableError` so the CLI can exit 1 with the
backend named.

**Problem**: The `yield` sat inside the `try`. In a generator-based context
manager, an exception raised in the **caller's** `with` body is re-injected into
the generator *at the yield statement* — so the handler intended for the
port-forward also caught every failure of the code the client was handed to. A
plain `RuntimeError` from `SreTriageEngine.diagnose_service` came out as:

```
✗ Could not triage api in prod: could not reach Grafana in prod: unexpected JSON payload from the Loki API
```

Both halves wrong at once: a **Loki** parse bug, blamed on **Grafana**, while
both port-forwards had succeeded and both backends were answering. An operator
reads the first clause and debugs a healthy service — the exact misattribution
the branch existed to remove, reproduced one level up.

The first repair was `except ObservabilityUnavailableError: raise`, added because
that class subclasses `RuntimeError` and was being double-wrapped. It looked
like "errors are not re-attributed". It asserted only that *one subclass* was
not re-attributed; every other `RuntimeError` still went out mislabelled. The
narrower claim is invisible at the call site, because the code reads as a guard
against re-attribution in general.

**Solution**: Structural, not a longer exception tuple — take the setup with an
`ExitStack` so the `try` covers only that, and put the `yield` outside it:

```python
with ExitStack() as stack:
    try:
        port = stack.enter_context(kubectl_service_port_forward(env, "loki", 3100))
    except ObservabilityUnavailableError:
        raise
    except (RuntimeError, TimeoutError) as exc:
        raise LogsUnavailableError(f"could not reach Loki in {env}: {exc}") from exc
    yield LokiClient(base_url=f"http://127.0.0.1:{port}")
```

`ExitStack` still tears the forward down on the way out, and an exception from
the caller's body passes through `__exit__` untouched because no handler of ours
is in its path. Proven by mutation: reverting `observability.py` to the previous
version fails
`test_an_engine_bug_is_not_relabelled_as_an_unreachable_backend` with the message
quoted above; restored, it passes. Found by adversarial review
(`agy/gemini-3.1-pro-high`, verdict FAIL) **after** #1595 had merged — so the
fix shipped as #1598 against `master`.

**Rule**: In a `@contextmanager`, put the `yield` **outside** every `try` whose
`except` is about setup. If the body must run inside a `with` (a port-forward, a
lock, a transaction), hold it with `ExitStack.enter_context` inside the `try` and
yield after it. A narrower `except` is not the fix: it would have to enumerate
every type the consumer might raise, and the consumer is not that function's to
know.

The general form, and the third instance of it in one day: *a guard that asserts
a subclass reads as a guard over the class*. Cf. [lesson 416](../ci-automation/lesson-416-a-guard-the-guard-must-assert-on-the-derived-artifact.md)
(an empty expectation matches everything) and [lesson 418](../process-method/lesson-418-a-before-after-probe-must-be-able-to-change.md)
(a probe that cannot change is inert). Same question settles all three: **what
would this check still pass on?**


**Tags**: `#python` `#contextmanager` `#error-handling` `#observability` `#adversarial-review` `#pr-1598`
