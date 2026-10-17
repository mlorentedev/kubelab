---
id: lesson-419-a-mutation-harness-runs-what-it-mutates
type: lesson
status: active
created: "2026-09-03"
owner: manu
category: process-method
tags: [kubelab, process-method, testing, verification, delivery]
---

# A mutation harness runs what it mutates, so a mutation can do the thing the code was written to prevent

**Context**: `#1596` adds `make promote-prod` and `make registry-prune`. Both
dispatch a workflow rather than doing the work locally, and that is the entire
design: `toolkit deployment promote --env prod` run on an operator's machine
edits the overlay in the working copy and stops, leaving a human to branch,
commit and push a production change by hand — no PR, no required checks, ADR-046's
gate bypassed by someone who believed they were using the supported path.

The test suite substitutes `GH=echo` so the dispatch is observable as text and
unobservable as an action, and seven mutations checked that each assertion could
fail. One of them replaced the dispatch line with the thing the target exists to
avoid:

```make
-	@$(GH) workflow run promote-prod.yml --repo $(DELIVERY_REPO) -f app=$(APP) …
+	@$(TOOLKIT) deployment promote --env prod --app $(APP) --version $(VERSION)
```

**Problem**: The suite ran it. `TOOLKIT` was not stubbed, because the recipe
under test did not use it — so `poetry run toolkit deployment promote --env prod
--app web --version 1.12.0` executed for real and rewrote two files:

```
 M infra/config/values/prod.yaml
 M infra/k8s/overlays/prod/generated/deployments.yaml
```

Nothing was committed and nothing was pushed; `git checkout --` restored both,
and the prod pin is `kubelab-web:1.1.1` as it was. But a test run had changed
production configuration on disk, and the tell was a timing one nobody would
read as a warning: that mutation took **5.14s** against 0.7s for the other six.

The stub was chosen against the recipe as written. A mutation's whole purpose is
that the recipe is no longer as written, so "which commands can this run" is
exactly the question a mutation invalidates — and the harness answers it once, up
front, from the unmutated file.

**Solution**: Neutralise every command variable the Makefile defines, not the
subset the current recipe happens to use:

```python
STUBBED = ("GH", "POETRY", "TOOLKIT")
subprocess.run(["make", *args, *(f"{var}=echo" for var in STUBBED)], …)
```

Mutation F now fails in 0.68s instead of 5.14s, which is the observable half of
it having stopped doing the work — and it is still caught, by two assertions.

**Rule**: A mutation harness executes the mutated code, so its isolation must
hold for code that does not exist yet. Stub by what the file *can* reach — every
command variable, every network client, every path a recipe could be edited into
— rather than by what it reaches today. The same applies to any test that
executes a script it also rewrites.

Two smaller things worth keeping. A mutation that takes seven times longer than
its siblings is doing something the others are not, and duration is the cheapest
signal that a supposedly inert run was not inert. And it is not an accident that
the mutation which escaped was the one representing the exact failure the code
prevents: the most dangerous mutation to run is the one that models the hazard,
which is also the one you most want to write.

Related: [`lesson-037` in `mlorentedev/web`] — verify that the mutation landed;
this is its other half, verify that it landed *and nothing else did*.

**Tags**: `#testing` `#verification` `#make` `#pr-1596`
