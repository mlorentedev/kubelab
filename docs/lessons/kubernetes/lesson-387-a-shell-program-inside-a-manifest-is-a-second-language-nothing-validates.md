---
id: lesson-387-a-shell-program-inside-a-manifest-is-a-second-language-nothing-validates
type: lesson
status: active
created: "2026-08-25"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes, gitops-delivery, observability, ci-automation]
---

# A shell program embedded in a manifest is a second language, and nothing in the delivery path reads it as one

**Context**: Demonstrating AC2 of #1377 on staging — the PVC alert had to be *shown* to fire when a PVC is genuinely unbound, not assumed. #1378's fix changed `disk-watcher`'s jq emitter from `healthy: (.status.phase == "Bound")` (a JSON boolean, which LogQL's `unwrap` drops) to `healthy: (if .status.phase == "Bound" then 1 else 0 end)`, and added a comment block explaining why.

**Problem**: The fixed CronJob never ran. The 02:45 job failed where 02:00, 02:15 and 02:30 had all completed on the old emitter. The cause was in the comment, not the code:

```
# A NUMBER, never `(.status.phase == "Bound")`. jq's `==`
# yields a JSON boolean, LogQL's `unwrap` needs a float, and
```

The jq program is passed as `jq -c '...'` — single-quoted **by the shell**. `jq's` and `LogQL's` each close that string. They are comments to jq and never reach it, because the shell finished the word before jq was handed anything. **The comment explaining the fix was what broke the fix.**

Nothing in the path noticed. `yamllint` saw a valid string; `kubectl kustomize` rendered it; `kubectl apply` accepted it; the Argo CD sync reported success. The manifest was *correct YAML describing a broken program*, and the first actor to evaluate the shell was the container itself — on a schedule, in a cluster, after merge.

Two amplifiers made it worse than a dead CronJob. `disk-watcher` feeds an alert whose `noDataState` is `Alerting`, so a watcher emitting nothing makes the alert **fire, looking correct, for the wrong reason** — a broken emitter and a genuinely unbound PVC are indistinguishable downstream, which is exactly the false positive AC2 exists to rule out. And a failed CronJob is silent: the Job goes `BackoffLimitExceeded`, the pod is deleted within seconds taking its logs, and no check asks whether the last run succeeded.

**Solution**: `sh -n` parses without executing, so the whole class is checkable statically, with no cluster, no images and no network. Extract `containers[*].args[0]` from every manifest and parse it. Measured with a control, which is what made the diagnosis certain rather than plausible:

```
master, old emitter    ->  sh -n  exit 0
#1378's branch         ->  sh -n  exit 2   Syntax error: word unexpected (expecting ")")
```

Landed as `tests/test_embedded_shell_syntax.py` (PR #1398), covering all six embedded scripts then shipping. Proven by mutation: with #1378's manifest in place it reports 1 failed / 6 passed and names the apostrophe; on master, 7 passed.

**Rule**:

- **A YAML string containing a program is two languages, and validators only read the outer one.** Every layer between the file and the container is a YAML tool. The inner language is evaluated exactly once, by the workload, in production. If a manifest embeds shell, something must parse it as shell before merge — `sh -n` costs milliseconds and needs nothing.
- **Prose inside a single-quoted program is a syntax hazard, and English is full of apostrophes.** "jq's", "don't", "LogQL's" all terminate the string. Put the rationale in the YAML comments *above* the block, where the shell never reads it: that removes the class rather than the instance.
- **`noDataState: Alerting` makes a dead producer look like a detected fault.** It is the right default for a metric that must never go quiet, and its cost is that "the alert fired" stops implying "the condition held". Before believing such an alert, check that its producer ran.
- **A drill can be more valuable when it fails than when it passes.** This one was set up to demonstrate an acceptance criterion and instead found the feature never executed. The lazy variant — scale the watcher down, watch the alert fire, screenshot it — would have "passed" and shipped the broken emitter, because it exercises the no-data path rather than the one under test. Same family as [lesson-382](../process-method/lesson-382-a-control-returning-the-same-code-as-the-real-attempt-measured-nothing.md), and as lesson-385 ("a drill gentler than the event tests the wrong branch") once PR #1387 lands it.

**Tags**: `#kubernetes` `#cronjob` `#jq` `#shell-quoting` `#alerting` `#pr-1398` `#pr-1378`
