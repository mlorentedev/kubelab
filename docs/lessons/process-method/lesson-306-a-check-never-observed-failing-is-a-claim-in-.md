---
id: lesson-306-a-check-never-observed-failing-is-a-claim-in-
type: lesson
status: active
created: "2026-08-09"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# A check never observed failing is a claim in executable syntax, not a check (AI-007)

**Context:** AI-007 retired Ollama across 38 SSOT surfaces. Two of its eight acceptance criteria carried the weight of the whole change — AC1 ("no live wiring survives in tracked files") and AC8 ("no operational document still describes it as running") — because a subtractive change has no feature to demo. Both asserted completeness the obvious way: search every tracked file, case-insensitively, for the word `ollama`; the criterion passes when the only matches fall inside a declared allowlist of paths.

**Problem:** Neither criterion could ever have passed, on the day it was written, for two independent reasons — and the failure was found by *running* them, not by reviewing them.

1. **`videollamada`.** The Calendly URL in `common.yaml`, and therefore both generated ConfigMaps, contains the substring `ollama`. Nothing about retiring an inference service can remove a Spanish word for "video call". The check was coupled to a coincidence of spelling.
2. **The check fires harder the better the work is.** After a complete sweep, every remaining match is either the ace2 teardown — which *must* name `/opt/ollama` and port `11434` in order to delete them — or a comment explaining why a catalog is now empty. A criterion asserting absence, written against a name, cannot distinguish a live reference from an explanation of its absence. Its false-positive rate is proportional to how thoroughly the retirement was documented.

Neither is a defect in the regex. Both are a category error about what was being asserted, and no amount of reviewing the criterion would have surfaced it: it reads as obviously correct, which is precisely why it was approved.

The second-order problem is the transferable one. There are two ways a verification fails to protect you, and they are not equally bad. A verification that **never runs** is visibly missing — someone eventually notices the gap. A verification that **runs and cannot fail** is strictly worse, because it *reports* protection: it occupies the slot where a real check would go, and it consumes the attention that would have written one. The green tick is the damage.

This exact shape appeared four more times in this repo inside a single week, which is what promoted it from an anecdote to a rule:

| Instance | What it claimed | Why it could not fail |
|---|---|---|
| `tls: {}` in the prod overlay | "no certResolver — `.local` can't get ACME certs" | an empty map in a strategic-merge patch changes nothing; prod retried an impossible LE order ~1/day for months while `config-check-drift` stayed green |
| `credentials hash-password` | prints `[SUCCESS]`, help says it writes SOPS | it prints the hash and tells you to edit by hand (#934) |
| CI-GATE-007 (#933) | pre-commit lints YAML | it only lints *changed* files, so `common.yaml` sat 21 errors red on master, invisibly |
| AC1 / AC8 | the sweep is complete | matched a coincidence and its own documentation |

The common ancestor is that every one of these compares **intent against intent**. Drift detection compares the committed overlay to the generator and finds them in perfect agreement; it has no way to notice that the agreed-upon intent does not do what its comment says.

**Solution:** Rewrite both criteria to assert the **identifiers that make the service reachable** — `ollama.kubelab.live`, `apps.services.ai.ollama`, `api-key-ollama`, `ollama/ollama`, `:11434` — instead of the word that names it. Prose about a retirement never contains an identifier that would make the thing live, so the check needs no allowlist and does not decay as documentation accumulates around it. A second probe (`f9`) was added asserting the **rendered** `kubectl kustomize` output of both overlays rather than the source tree, on the same reasoning that produced the `tls: {}` bug: a clean source still emits through a base or a patch.

**Rule:** **Run every verification command once against a state where it is expected to FAIL, before trusting it.** A negative control costs one command — `git stash`, re-add the line, point it at the pre-fix commit — and it is the only evidence that separates a check from a sentence. Until a check has been observed going red, its green is unfalsifiable and means nothing.

Three corollaries, each of which independently killed one of the cases above:

- **Assert the identifiers that make a thing work, not the string that names it.** Names appear in explanations, comments, changelogs and unrelated words; identifiers appear only in wiring.
- **Assert rendered output, not source.** Verify by reading what the system emits (`kubectl kustomize`, the generated ConfigMap, the live object), never by reading the patch or the config that was supposed to produce it.
- **A check that only inspects what changed cannot report on what is already broken.** Scoping a gate to the diff is a performance decision that silently becomes a correctness one.

**Tags:** `#verification` `#negative-control` `#acceptance-criteria` `#spec-driven-development` `#silent-failure` `#grep` `#false-positive` `#ai-007` `#ci-gate-007` `#gotcha`
