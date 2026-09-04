---
id: lesson-388-a-decision-reaches-only-as-far-as-the-artefact-at-the-point-of-use
type: lesson
status: active
created: "2026-08-25"
owner: manu
category: process-method
tags: [kubelab, process-method, knowledge, adr, gitops-delivery]
---

# A decision reaches only as far as the artefact someone opens at the point of use — three re-derivations in one session

**Context**: A single session touched three unrelated areas: validating a change on staging, deciding whether the Go API is a platform service, and sequencing the knowledge-plane backlog. Each began by working out an answer from scratch. Each answer already existed, written down, accepted, and in two cases carrying an open ticket.

**Problem**: The re-derivations were not caused by missing documentation. They were caused by the artefact at the point of use still asserting the superseded thing.

| Re-derived | Already written | What the point of use said |
|---|---|---|
| `selfHeal: false` does not stop a revision-triggered sync | [lesson-330](../gitops-delivery/lesson-330-staging-s-selfheal-false-doesn-t-stop-argo-cd.md) (2026-08-15), ticket #1083 open | `staging.yaml:40`: *"selfHeal: false — staging is a mutable test bed"*, restating the disproved guarantee. CLAUDE.md and ADR-058 repeated it. [lesson-256](../gitops-delivery/lesson-256-2026-05-12-argo-cd-targetrevision-preview-pat.md), which holds the technique that *does* work, was marked "superseded by ADR-037" — advice inverted, since the superseding decision is the one that failed |
| Whether `apps/api` is a website backend or the platform API | ADR-057 (accepted 2026-06-26), ADR-048 before it | `go.mod` said `module github.com/mlorentedev/mlorente-backend`; the README said *"the backend for my personal website"*; `common.yaml` said *"Stream C will extract the API"* — an extraction ADR-048 rejected |
| Why the knowledge-plane tickets had not moved in two months | #606 states *"Feeds IDP-027 (#395)"* | #606 is filed as WEB-015 inside epic WEB-010 while #395 is IDP-027, so from the IDP side the hard dependency is invisible; and #375's first line still specified a proxy to an Ollama that AI-007 retired on 2026-08-09 |

ADR-057 had even **predicted its own case**: *"The recurring question ('should the API be central? move it to web? rewrite it in the frontend's language?') is a symptom of this missing boundary."* The question recurred, from someone reading the module path, two months after the ADR that answered it — because the ADR's own Implementation section listed "reposition `apps/api` identity (README + service description)" as a follow-up and **that follow-up was never filed**.

The cost is not only the time. A re-derivation reaches the same conclusion **or a different one**, and nothing reconciles the two. The staging case nearly produced a fourth mechanism for a problem that already had a decision ticket.

**Solution**: For each, correct the artefact rather than only recording the finding again — the correction is small and it is the part that was missing.

- PR #1396 — `staging.yaml` header and flag comment, ADR-037 (as an amendment, since the original bullet already knew the mechanism and misjudged the consequence), ADR-058, CLAUDE.md, and lesson-256's supersession header.
- PR #1397 — module renamed to `github.com/mlorentedev/kubelab/apps/api`, README rewritten, `common.yaml` comment corrected.
- #1401 (IDP-037) — a sequencing ticket holding the order, plus reverse cross-links on #395/#606/#299 and a rewritten premise on #375.

**Rule**:

- **A decision is delivered when the artefact someone opens at the moment of acting says it — not when the ADR is accepted.** ADRs are the record; `go.mod`, a flag comment, a ticket's first line and CLAUDE.md are the delivery.
- **"Follow-ups are separate tickets" is where decisions go to die.** An ADR that ends with a follow-up list and files none has documented an intention. File them in the same session, or write the decision into the artefact directly.
- **A supersession note is a claim that can go stale, and it goes stale backwards.** When B supersedes A and B is later disproved, A's header still points at B. Both lesson-256 and ADR-037 pointed the reader at the failed decision. When disproving something, check what it superseded.
- **A hard dependency declared on one side only is invisible from the other.** Cross-epic links especially: #606 said it feeds #395, and from #395 nothing said so. Write both directions or neither is real.
- **The tell is a question that keeps coming back.** A recurring question is not a memory problem; it is an artefact still giving the old answer. When one recurs, fix what is answering — do not just answer it again.

## Fourth occurrence — 2026-09-04, and this one had already generated backlog

Recorded here rather than as a new lesson: the rule above was written on
2026-08-25 and this is the same failure, so a second lesson would be an instance
of the thing the rule warns about.

`CLAUDE.md:119` still said *"Argo CD Image Updater (Phase 3) will automate this"*
and told the reader to hand-edit `infra/k8s/base/kustomization.yaml` after a
release — the edit the drift gate exists to reject. **ADR-046 D4 descoped Image
Updater on 2026-06-14** after a four-way audit, and the descoping was filed and
closed correctly as `#692`. The tracker was right; the file every agent loads at
session start was not.

Two costs, and the first is what makes this occurrence worth adding:

- **2026-08-09 — the stale line generated a ticket.** `#929` was filed quoting it
  verbatim as its evidence: *"`CLAUDE.md` already names the intended tool and
  treats it as planned work… but no issue tracks it."* Backlog created for work a
  decision had already declined, citing the doc as the authority.
- **2026-09-04 — the question came back**, and answering it produced **two
  recommendations ADR-046 had already rejected**: a direct push to `master`
  (impossible under `enforce_admins: true`, stated in the ADR's own amendment) and
  removing staging's PR gate (contradicts ADR-037's mutable-test-bed semantics).
  Both retracted only after someone went looking for the ADR.

Fixed in `#1612`; `#446` and `#498` closed as superseded and done.

**One extension to the rule.** The sweep found a shape the earlier cases did not
cover. A supersession note goes stale *backwards* — that is already above. This
goes stale **forwards**: ADR-038 defers a Sealed Secrets evaluation behind the
trigger *"Argo CD Image Updater landed (ARGO-014) **and** …"*, and ARGO-014 is now
closed as descoped. **A deferred decision whose revisit condition can no longer be
met is not deferred; it is silently final**, and nothing in the ADR says so
(`#1613`).

So when an ADR supersedes a mechanism, grep the mechanism's name and triage every
hit: leave it in superseded ADRs (that is history), correct it in agent- and
operator-facing docs (this is the bucket that generates backlog), and **ticket it
where it appears as a live trigger inside another active ADR**.

**Tags**: `#process` `#knowledge-placement` `#adr` `#point-of-use` `#pr-1396` `#pr-1397` `#issue-1083` `#issue-1401` `#pr-1612` `#issue-1613` `#issue-929`
