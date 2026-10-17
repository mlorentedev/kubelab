---
id: lesson-428-a-sample-is-not-the-population-say-which-frame-you-measured
type: lesson
status: active
created: "2026-09-04"
owner: manu
category: process-method
tags: [kubelab, process-method, verification, mutation-testing, tool-063]
---

# A sample is not the population — state the frame next to the verdict

**Context**: One day's work on TOOL-063 (#1633, Gitea repository settings) and, in
parallel, on #1583 AC3 (Grafana alert-rule orphans). Four independent checks, two
agents, two domains.

**Problem**: Each check produced a verdict that read as a property of a whole
population, and each had silently measured a sample of one. All four erred toward
a *cleaner* answer than the truth.

| The check | The frame it actually had | What it would have concluded |
|---|---|---|
| "may the bot configure repositories?" | one repository | yes — it answered **200** |
| "does this guard hold under mutation?" | a file the mutation never edited | yes — "88 passed" |
| "does the loader refuse an absent block?" | a substring two branches print | yes — it raised, naming the key |
| "is this alert rule an orphan?" | one 11h window; `max()` over `{"5m","10m","15m"}` | yes — 0 evaluations |

The first is the sharpest. `PATCH /repos/{o}/{r}` as the bot returned **200** on
`teledyne/openkm-brain` and **403** on the other two — and the variable was not the
credential, it was the **provenance** of each repository. Gitea makes a repository's
creator its admin; `openkm-brain` was the empty shell the bot itself had created,
while the other two were migrated by the superadmin, leaving the bot only its team's
`write`. Sampling that one repository would have "established" a capability the bot
does not have, and the reconciler would then have failed on exactly the repositories
that hold content.

The second is the most embarrassing, because the tool was *built* to avoid the
first. A mutation harness reported six mutations caught; one of them had replaced a
string that `ruff` had since reformatted across three lines, so it edited nothing
and the suite passed for the only possible reason. "The guard held" and "there was
nothing to hold against" render identically in `88 passed`.

**Solution**: Two mechanical habits, both cheap.

**Verify the sample exists before reading the result.** One line closed the second
row:

```bash
if git diff --quiet; then echo "MUTATION DID NOT APPLY — result is meaningless"; return 1; fi
```

Applied afterwards, it re-ran all six: five had genuinely applied, and the sixth was
a real survivor — the loader test whose assertion two different `ValueError` paths
satisfied. That one was invisible to reading and to review; only the mutant found it.

**State the frame in the same sentence as the verdict.** Not in a comment, not in
the commit body — in the published claim, so the reader can size it:

> prod, 11h34m window, slowest declared group interval 15m, 10 of 10 current rules
> observed evaluating, retired rule 0 times.

The zero is only readable because the non-zeros are in the same log. A bare "0
evaluations" is a number with no denominator.

**Rule**: Before reporting what a check established, ask **what varied and what did
not**. A capability probe over one target measures that target's history. A mutation
run over an unmutated file measures nothing. An assertion on a substring measures
every branch that prints it. A window measures the window.

This is [[lesson-425]]'s twin turned sideways: 425 is about **depth** — a probe that
stops at the first of several gates. This is about **breadth** — a probe that crosses
every gate, once, on one member of the population. Both produce a true statement
about something narrower than the question asked.

**Corollary, and the reason the habit pays rather than merely costs**: a guard built
on this principle earned its keep the same afternoon. `ensure_settings` re-reads a
repository after PATCHing it instead of trusting the 200, and the first `--apply`
against prod went **red on all three repositories** — Gitea had applied `has_wiki`
and `has_projects` and silently ignored every merge field, because those live behind
the `has_pull_requests` unit flag. Measured, once the read-back said to look: the
same body without that flag applies **0/6**, with it applies **6/6**. Without the
post-condition the run would have reported "settings applied" over a forge that
still merges with merge commits, and every later run would have agreed.

Related: [[lesson-423]] (a fake cannot verify a request), [[lesson-416]] (an empty
expectation matches everything), [[lesson-424]] (convergence scoped to the creation
diff).

**Tags**: `#verification` `#mutation-testing` `#sampling` `#gitea` `#tool-063`
