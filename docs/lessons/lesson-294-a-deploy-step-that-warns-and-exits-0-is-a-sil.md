---
id: lesson-294-a-deploy-step-that-warns-and-exits-0-is-a-sil
type: lesson
status: active
created: "2026-07-09"
owner: manu
tags: [kubelab, lesson, cli, exit-code, silent-failure, kubernetes, rollout, fail-closed, tool-021, gotcha]
---

# A deploy step that warns and exits 0 is a silent failure — the exit code is the only thing the next step reads (TOOL-021)

**Context:** TOOL-021 (#838), from the process audit (P6). `infra k8s deploy` applied the manifests, then ran `kubectl rollout status … --timeout=120s` as a final check.

**Problem:** Every earlier step in the command failed closed (`raise typer.Exit(1)`), but the **rollout wait only logged a warning and returned 0**. So a deploy that left pods CrashLooping reported success. That matters precisely because nothing downstream reads the log: `make deploy-k8s && <next step>` proceeds, CI goes green, and an agent chaining on the exit code marches on over a broken cluster. The failure is loud to a human watching the terminal and completely invisible to every automated consumer.

**Solution:** Fail closed on a non-zero rollout — log the stderr, print a `make logs SVC=<name> ENV=<env>` pointer so the next step is obvious, and `raise typer.Exit(1)`. Made the **default**, not an opt-in `--strict`: a healthy deploy rolls out well inside the 120s timeout, so the only thing an opt-in flag buys is the chance to forget it. Covered by two TDD tests.

**Rule:** In any CLI meant to be chained, the **exit code is the contract** — a warning is a comment, not a signal. If a step's failure invalidates the steps after it, it must be non-zero by default; "strict mode" as an opt-in just relocates the silent failure to whoever didn't pass the flag. Audit the last step of every command specially: it's the one that most often degrades to a warning because "the real work already succeeded".

**Tags:** `#cli` `#exit-code` `#silent-failure` `#kubernetes` `#rollout` `#fail-closed` `#tool-021` `#gotcha`
