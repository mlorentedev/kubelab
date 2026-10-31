---
spec: "ANSIBLE-086-rootless-download-attempts"
verdict: "PASS"
reviewed_sha: "5481b860006b772bb17f56b11c066038b2ed5f7b"
reviewer: "nan/deepseek-v4-flash"
date: "2026-10-30"
---

## Adversarial review

**Scope**: `ANSIBLE-086-rootless-download-attempts` — `git diff 98c3cd5634a44248709ee1c0d5d92bab43eabe74...HEAD`
(8 commits, 321 files). The spec's own work is confined to `14454341` (#2855, +283/−36,
16 files) and `3cb1aaa6` (#2869, +113/−55, 5 files); the remaining ~2.4k changed lines are
unrelated PRs merged into the span (#2864 encoding, #2838 beelink binfmt, #2867 node_notify,
#2871 NOTIFY-012 archive, VPN-ACL-014). I judged the two spec commits' surface and did **not**
judge the other PRs' correctness — they belong to their own specs.

**Sources**:
- `specs/ANSIBLE-086-rootless-download-attempts/spec.md` (the only contract file in the folder)
- `infra/config/values/common.yaml`, `infra/ansible/playbooks/_includes/image-pull.yml`,
  `infra/ansible/roles/{docker,agent_stack}/tasks/*.yml`, the seven `provision-*.yml` /
  `deploy-dns.yml` plays, `tests/test_image_pull_budget.py`
- no PR reference was supplied; the diff is the artifact

**Environment note**: `proposal.md`, `tasks.md` and `verification.md` do not exist for this spec
(FTD lane, single `spec.md`), so the acceptance criteria are taken from `spec.md` §Scope/§Checklist.
`review-request.json` records empty `contract_digests` for all three contract files — see finding
F2.

### Spec and task alignment

| Spec claim (`spec.md`) | Code / evidence | Verdict |
|---|---|---|
| `networking.edge.uplink.max_download_attempts: 40` | `common.yaml:86`, under `uplink`, sibling of `bandwidth` — name matches exactly | holds |
| `networking.edge.uplink.bandwidth.pull_goodput: 0.54` | `common.yaml:76` | holds |
| Every play running the docker role or agent_stack sets the attempts from that key | 5 plays reference `roles/docker` or `roles/agent_stack`; all 5 set `docker_max_download_attempts` from the SSOT. `provision.yml` sets it at play level for `all`; the role fires only on `docker_hosts` | holds |
| Every play that sets `image_pull_down_kbit` sets `image_pull_goodput` | 7 plays set the downlink (`ace1`, `ace2`, `bee`, `rpi3`, `rpi4`, `deploy-dns`) and all set the goodput | holds |
| docker role renders it into `/etc/docker/daemon.json` | `roles/docker/tasks/main.yml:102` — `"max-download-attempts": {{ docker_max_download_attempts | int }}`, with **no** role default | holds |
| agent_stack renders it into the agent user's `daemon.json` | `roles/agent_stack/tasks/agent_user.yml:171-186`, `~/.config/docker/daemon.json`, one key only | holds |
| The reload + read-back was removed (F1 of the previous round) | no `daemon-reload`, no `StartedAt` read anywhere in `agent_user.yml`; `3cb1aaa6` removed 46 lines | holds |
| Include divides the estimate by the goodput | `image-pull.yml:55` divides by `image_pull_goodput \| default(1)` | holds |
| Include adds `5·n(n−1)/2` to the attempt bound | `image-pull.yml:57-59` computes `5*n*(n-1)//2`; `:110` adds it to the `async` value | holds |
| rpi3 keeps Docker's 5, ticketed | `provision-rpi3.yml:64-66` deliberately omits the var; the include's `default(5)` matches; ticket **kubelab#1032 is OPEN** ("ANSIBLE-036: rpi3's Docker install is unmanaged") | holds |
| Follow-up store question ticketed | **kubelab#2868 is OPEN** ("ANSIBLE-087: the rootless daemon's image store reads no download attempts") | holds |
| `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags | none in `spec.md` | clear |

### Verification I ran (fresh, this session)

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest tests/test_image_pull_budget.py -q` | **35 passed** in 20.60s |
| `… tests/test_ansible_syntax_check.py tests/test_edge_ssot.py tests/infra/test_network.py tests/test_ansible_ssot_paths.py` | **31 passed, 5 deselected** |
| `… tests/test_lesson_index_integrity.py tests/test_lessons_index_is_derived.py tests/test_check_lessons.py` | **108 passed** |
| `dotf spec digest ANSIBLE-086-rootless-download-attempts` | three keys, all values `""` (see F2) |
| `gh issue view 1032` / `2868` | both OPEN, titles match what the spec claims |

Mutation checks (each applied, run, reverted; tree clean afterwards — `git status` shows only this
review and `review-request.json`):

| Mutant | Test that went red |
|---|---|
| drop `+ (_image_pull_pauses \| int)` from the `async` bound | `test_the_bound_covers_dockerds_pauses_and_the_estimate_its_goodput` |
| drop `/ (… * image_pull_goodput …)` from the estimate | `test_the_bound_covers_dockerds_pauses_and_the_estimate_its_goodput` |
| remove `docker_max_download_attempts` from `provision-ace2.yml` | `test_every_play_behind_the_edge_passes_the_edges_values` |
| render a literal `5` in the agent's `daemon.json` | `test_both_daemons_render_the_one_attempts_value` |
| `vars: docker_max_download_attempts: 5` on the docker role entry in `provision.yml` | `test_nothing_overrides_the_edges_values_the_plays_pass` |

The fifth mutant is the one the previous round's F5 fix added; it does bite. (First attempt at it
survived because the insertion produced a duplicate `vars:` key that PyYAML silently drops — a
lesson about writing that mutant, not about the test.)

**Not verified by me**: the live run the checklist quotes
(`make provision NODE=ace2 ENV=prod TAGS=agent_stack … ok=212 changed=0`, reload event reading 40,
`StartedAt` unchanged). I have no ace2 access; that evidence is the author's and I can only note
that it is dated, specific and reproduced with `changed=0`. `make lint-ansible` is delegated to the
`toolkit` CLI, which is not runnable as `python -m toolkit`; the equivalent parse coverage came
from `tests/test_ansible_syntax_check.py` instead.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|--------------|
| Minor | THEORETICAL | budget vs bound | The refusal still compares only the *transfer* estimate with `image_pull_budget_seconds` (`image-pull.yml:79-83`), while the attempt bound it now grants adds up to 65 min of pauses. A pull whose estimate sits under the 30-min budget is admitted and may then run ~95 min before `async` kills it — the exact "budget says X, reality says 4X" mismatch the Intent names for the estimate, left in place for the budget. | `_decide(2970, 100_000_000)` = admitted at 270 s estimate against a 1800 s budget, bound `270*2+300+50`; at `docker_max_download_attempts=40` the same call's bound grows by 3900 s with the budget check unchanged | **UNTESTED** — `test_a_pull_past_the_budget_is_refused_unless_the_run_allows_it` and `test_the_bound_covers_dockerds_pauses_and_the_estimate_its_goodput` each exercise one half, never the interaction | code + tests, or a stated decision in `verification.md` that the budget is transfer-only |
| Minor | THEORETICAL | gate staleness | The spec has no `proposal.md` / `tasks.md` / `features.json`, and `review-request.json` carries `""` for all three `contract_digests`; `dotf spec digest` reproduces the empty values. The archive gate therefore has nothing to compare, so an edit to `spec.md` after this review cannot be detected as staleness. | `dotf spec digest` output; folder listing | None (tooling) — no named test | spec/tooling: either digest `spec.md` for FTD specs or declare the check not applicable |
| Minor | SPECULATIVE | dead-by-admission config | `agent_stack` now writes a `daemon.json` whose single key the containerd image store ignores (#2868). The file is written on every run and nothing observes it; its value depends on a store change that is only a ticket. That is forward-compat by declaration, not by evidence — the only proof the daemon tolerates the file is the author's ace2 run. | `agent_user.yml:163-186`; comment states the key has no effect | `test_both_daemons_render_the_one_attempts_value` proves the *content*, not that the daemon starts with it | none required; surface only |
| Question | SPECULATIVE | measurement basis | `pull_goodput: 0.54` comes from one refill on one node (Open WebUI, ace2). Every sized play now divides by it, including rpi3's Wi-Fi pulls and the gateway's. A second concurrent pull would share the shaper and sit below 0.54, so the estimate is a best case. Confirmation wanted: is "under-estimate the time" the accepted direction? | `common.yaml:71-76` comment cites #2703 | `test_a_pull_gets_a_share_of_the_downlink_and_no_more` (bounds only) | spec note, or leave as the measured value with the comment's "re-measured with the site" caveat |

No Blocker and no REAL Major: the acceptance criteria hold under the tests I ran, the five claimed
mutants are red, and the two out-of-scope items the spec admits are both ticketed and open.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | Every criterion in `spec.md` maps to code I read and a named test I ran green; negative paths (unset goodput → 1, `down_kbit=0` → fixed 3600 s bound, `goodput>1`/`0` rejected, held image) are covered; no defect observed. |
| Verification       | B | Named, reproducible tests carry the change and five mutants are red; the decisive live evidence (`ok=212 changed=0` on ace2) is the author's and I could not reproduce it. |
| Scope              | B | The spec's two commits touch exactly the surface the proposal names; the review span additionally carries ~2.4k lines of other merged PRs, documented above and not judged here. |
| Reliability        | A | Missing attempts var now fails loudly instead of silently leaving Docker's 5; unconfigured daemons fall back to 5 consistently; the rootless file is deliberately one key to avoid a startup-blocking flag conflict; role is idempotent (`changed=0` reported). |
| Maintainability    | B | Long `why` comments everywhere, tests well named, but the play-scanning helpers (`_set_above_play_vars`, `_task_sets`, `_vars_file_keys`) are ~25-line multi-branch functions and the include's Jinja bound is now a four-term expression readable only with the comment beside it. |
| Handoff-readiness  | A | `spec.md` records scope, checklist, evidence and promotion candidates; two lessons added and indexed (108 lesson tests green); follow-up ticketed as #2868; no `[AGENT-DRAFT]` tags. |

Aggregation: no D, no C → **PASS**. Severity path agrees: minors only, none REAL.

### Verdict

**PASS (adversarial)**

`dotf spec archive` is **advisable** in this state: this review is fresh for the contract as it
stands, no Blocker or REAL Major is open, and the two caveats (F1's untested budget/pause
interaction, F2's vacuous digest pair) are tracked below rather than blocking.

### Recommended next steps

The contract set (`spec.md` here; `proposal.md`/`tasks.md`/`features.json` do not exist) is
**closed** by this verdict — do not edit it. Disposition the following in `verification.md`, which
the staleness check ignores, or carry them into a ticket:

1. **F1 (budget vs pauses)** — decide and record: is `image_pull_budget_seconds` a transfer-only
   budget (then say so in the include's comment next to the refusal) or a wall-clock budget (then
   refuse on `_image_pull_seconds + _image_pull_pauses` and add the named test)? Either is a valid
   answer; leaving it unstated is what F1 is about. If it needs code, that is a follow-up, not a
   condition of this archive.
2. **F2 (empty contract digests)** — note in `verification.md` that the archive's staleness check
   is vacuous for a single-`spec.md` FTD spec; if the tooling should digest `spec.md`, file it.
3. **F3 (no-op rootless config)** — no action required while #2868 is open; if #2868 lands and
   changes the store, revisit whether `agent_user.yml` still needs a file, and whether the
   daemon's tolerance of it deserves a test of its own.
4. **F4 (goodput basis)** — answer the question above in the follow-up for #2868 or in
   `verification.md`; no code change implied.
