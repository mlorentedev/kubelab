---
spec: "ANSIBLE-066-pinned-host-keys"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "fa2da3380015158b25747f141adbd992aaf5f168"
reviewer: "nan/deepseek-v4-flash"
date: "2026-10-14"
---

## Adversarial review

**Scope**: `ANSIBLE-066-pinned-host-keys` (#2223) — `git diff e852af85d4f6fb84e5b68d021819b773b3f1b646...HEAD` (HEAD `fa2da338`), the whole change.
**Sources**: `specs/ANSIBLE-066-pinned-host-keys/{proposal,tasks,verification,features}.md`; `toolkit/features/generator_ansible.py`; `toolkit/cli/infra.py`; `tests/test_ansible_pinned_host_keys.py`; `tests/test_generator_ansible.py`; `infra/config/values/common.yaml`; `infra/ansible/inventories/homelab.yml`; `docs/runbooks/add-a-node.md`; `docs/lessons/ansible-provisioning/lesson-569-*.md`.

### Spec and task alignment

- **AC1 (pinned file for every stable host, mesh + bootstrap)** — met. `AnsibleGenerator._pinned_ssh_args` builds `-o StrictHostKeyChecking=yes -o UserKnownHostsFile={networking.ssh_known_hosts}` and it is the inventory-global `ansible_ssh_common_args`; the SSOT path sits beside `ssh_key` in `common.yaml`. Re-ran the real SSOT: global args are the strict string in mesh, bootstrap and bastion, and only `gcp1` carries a per-host override. `test_every_stable_host_is_verified_against_the_pinned_file[mesh|bootstrap]` + `TestTheSsotDeclaresThePinnedFile` pass.
- **AC2 (only the by-design node keeps TOfU, derived from the SSOT shape)** — met, and derived rather than listed: `ephemeral: not tailscale_ip` is set on the hub nodes, `_host_vars` turns it into `TOFU_SSH_ARGS`, and `TestTheHubException` asserts both directions (add a `tailscale_ip` → the exception is lost). Non-vacuous (`assert ephemeral`).
- **AC3 (bastion: jump and hop both verified; hub keeps its override on the hop only)** — met at the generator level. `_bastion_ssh_args` now emits only `-o ProxyCommand="… {pinned} …"` and `_host_vars` prefixes the host's own key args, producing two `UserKnownHostsFile=` occurrences for a proxied stable node and `accept-new` outside the proxy for the hub. Verified by dumping a real bastion inventory.
- **AC4 (refuse before invoking ansible-playbook, naming the file)** — met. `_missing_known_hosts_file` reads the inventory that will run (so `--skip-generate` is covered) and `ansible_run` exits non-zero at `toolkit/cli/infra.py:1471` before building the command.
- **AC5 (committed `homelab.yml`)** — met. Args are the strict string, no `accept-new` anywhere in the file, guarded by `test_the_committed_inventory_never_trusts_on_first_use`.
- **AC6 (live)** — manual evidence in `verification.md`, not re-run (would open sessions to the live fleet). Corroborated from this workstation: `~/.ssh/known_hosts_pinned` exists with 10 lines, and `ssh-keygen -F` finds every address this inventory uses, including the VPS public IP `162.55.57.175` that the `vps` host and the bastion jump both connect to. One wording mismatch (finding 6).
- **AC7 (runbook + corrected comments)** — met in substance: `docs/runbooks/add-a-node.md` puts pinning (steps 1–3) before the first provisioning run (step 4), and `wait-node-ready.yml`, `gcp-hub-bootstrap.md` and the wait-node-ready test no longer say the inventory uses `accept-new` fleet-wide. The runbook cannot be followed end-to-end as written (finding 2).
- **Task boxes**: every implementation box in `tasks.md` has diff evidence. The two unticked boxes are the draft PR and `dotf spec review`/archive — correct for this phase. No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags remain.
- **Evidence reproduced in this session**: `poetry run pytest -q -m "not e2e and not infra and not integration"` → **4595 passed, 18 skipped, 176 deselected, 2 xfailed** (matches `tasks.md`); all `features.json` verification commands re-run green (f1 3 passed, f2 2, f3 2, f4 2, f5 1, f7 8); `poetry run mypy toolkit` → clean (127 files); `ruff check`/`format --check` on `toolkit/` and every changed file → clean.
- **Test deletions (retention bar)** — `test_global_ssh_args_unchanged` (deleted) pinned the inventory-global args to the old `accept-new` value; its replacement `test_every_stable_host_is_verified_against_the_pinned_file` asserts the same seam against the new contract. Shown, not assumed: reverting the hub exception (`host_key_args = pinned_args`) turns 2 tests red, and pointing the bastion jump back at `accept-new` turns `TestBastion` red (mutations applied and reverted, `git status` clean). No non-test caller depends on the removed assertion; history: `git log -S` traces it to `e5639c1d` (bastion transport) and its removal to `c490e717`. `test_no_per_host_proxy_in_mesh` was narrowed, not deleted — "per-host args exist only for the by-design node" is asserted exactly by `TestTheHubException`.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL (the skip is REAL, the exploit is argued) | security-residual | Verification is the policy but multiplexing is left on: the inventory never sets `ControlMaster=no`, and with no `ansible.cfg` in the repo Ansible's default `ssh_args` (`ControlMaster=auto`, `ControlPersist=60s`) applies, so a connection to the same host within 60s of any earlier task opens no session and checks no host key. Consequence argued, not observed, for a *stable* node: the socket points at the machine that was already verified, so a wrong key is trusted only if the address is re-pointed inside the window. What is demonstrated is the false pass — `lesson-569` measured rpi3 answering with a swapped key, and AC6's own evidence needed `-o ControlMaster=no -o ControlPath=none` to make the negative run mean anything. Matters because the spec is SEC-033's declared prerequisite ("verify before editing `authorized_keys`"). | `lesson-569` (reproduction of the skip); `verification.md` AC6 (multiplexing disabled by hand); `grep -r ansible.cfg` → none; `toolkit/features/generator_ansible.py:141` | UNTESTED | code (or an explicitly accepted residual — I would track rather than block: the baseline was `accept-new` for the whole fleet, so this is strictly stronger, and the exposure is narrower than the criterion it replaces) |
| Minor | REAL | docs / runbook | `docs/runbooks/add-a-node.md` step 4 says `make provision NODE=<name>`, but a run requires `infra/ansible/playbooks/provision-<NODE>.yml` and the runbook never says to create one; for an existing node the playbook suffix is not the node key (`beelink` → `NODE=bee`). Followed literally, step 4 dies at "Playbook not found" before it reaches the pinning this spec is about. | `ls infra/ansible/playbooks/` (per-node `provision-*.yml`, incl. `provision-bee.yml` whose own usage is `NODE=bee`); `toolkit/cli/infra.py:1454`; f7's "test" is only `test -f docs/runbooks/add-a-node.md` | UNTESTED | docs |
| Minor | THEORETICAL | tests | `TestBastion::test_the_hub_keeps_its_exception_on_the_proxied_hop_only` loops over `_ephemeral_hostnames(net)` with no non-vacuity guard, unlike its two siblings; if the SSOT ever stops declaring an ephemeral hub (e.g. a hub given a reserved `tailscale_ip`), it passes while asserting nothing. | code read of the test; sibling guards at `test_ansible_pinned_host_keys.py:67` (`assert stable`) and `:82` (`assert ephemeral`) | UNTESTED (the gap is inside the named test) | tests |
| Minor | THEORETICAL | resilience | `_missing_known_hosts_file` assumes `ansible_ssh_common_args` is a `str`; Ansible also accepts a list for that variable, so a hand-edited or `--skip-generate` inventory raises an unhandled `TypeError` (and a malformed file an unhandled YAML error) instead of the clean refusal the function exists to give. | code read, `toolkit/cli/infra.py:1399-1412` | UNTESTED | code |
| Minor | THEORETICAL | behavior | The preflight reads only `all.vars`, so `make wait-node-ready NODE=gcp1 ENV=hub` — the recreated-hub path, where every targeted host is TOfU by design — is still refused when the pinned file is absent, although a pin is not needed there. Softened by the declared prerequisite (dotfiles deployed on the controller). | generator dump: the hub's per-host args carry no `UserKnownHostsFile`; preflight regex matches the global value only | UNTESTED | code |
| Minor | REAL | spec / evidence | AC6 claims "a read-only play (`ping`) against every stable node succeeds"; jetson's `ping` fails (Python 3.6) and `raw` is substituted, so the criterion as written is unmet for one node, and "6 of 6 stable nodes" is inconsistent with the 7 stable hosts the inventory emits (ace1, ace2, beelink, jetson, rpi3, rpi4, kubelab-vps). Disclosed in the same bullet, so this is evidence wording, not a hidden failure. | `verification.md` AC6; `lesson-569` ("6 of 6"); generator emits 7 stable hosts | UNTESTED (manual AC) | spec (verification.md — outside the contract set) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Every criterion is met on the security-critical path and the negative paths are covered (hop must not TOfU, exception is bounded, missing file refuses); small gaps: one vacuous test and the AC6 wording. |
| Verification       | B | Evidence is reproducible and I reproduced it (full suite, each `features.json` command, mutations); the live half is manual and cannot be re-run without touching the fleet, and its own method needed a hand-added option. |
| Scope              | A | Diff matches the proposal: three implementation commits plus the spec/docs; the `gcp-hub-bootstrap.md`, `wait-node-ready.yml` and `platform.json` touches are AC7 and the SSOT-sync test, not creep. |
| Reliability        | B | Fail-fast preflight, idempotent generation, no destructive path; the untyped-inventory edge and the global-only read are gaps. |
| Maintainability    | A | Short single-purpose functions, WHY comments on the non-obvious branches (why the VPS jump stays strict, why `ephemeral` is derived), mypy strict and ruff clean on every changed file, no dead code. |
| Handoff-readiness  | B | `verification.md` + `features.json` filled, lesson-569 written and indexed, runbook added; the runbook cannot be executed as written, which is exactly the handoff artifact. |

### Verdict

PASS WITH GAPS

Mechanical basis: no Blocker, no D and no C on the rubric; the only Major is THEORETICAL (the reproduced half is the *skip*, argued through `lesson-569`, not a demonstrated wrong-key connection in production). Findings 1–6 are tracked below with a disposition each.

### Recommended next steps

All of these are outside the contract set (`proposal.md`, `tasks.md`, `features.json`), which this verdict closes — an edit to any of the three invalidates this review.

- **Finding 1 (multiplexing)** — disposition it in `verification.md` in one line: either "ticketed as #NNNN to set `ControlMaster=no` on the generated inventory when the goal is a verified connection", or "accepted: the socket points at the host already verified, and `lesson-569` carries the caveat". Do not silently leave it only in the lesson.
- **Finding 2 (runbook)** — add the missing step to `docs/runbooks/add-a-node.md`: create `infra/ansible/playbooks/provision-<node>.yml` (copy a sibling, e.g. `provision-bee.yml` for `beelink`), and say that `NODE` is the playbook suffix, not the `hostname`.
- **Finding 3 (vacuous test)** — add `assert ephemeral` to `TestBastion::test_the_hub_keeps_its_exception_on_the_proxied_hop_only`, mirroring its siblings.
- **Finding 4 (preflight types)** — either coerce non-string args to `""`, or catch the parse errors and log the file instead; a two-line guard plus one test with a list-valued `ansible_ssh_common_args`.
- **Finding 5 (global-only preflight)** — decide and record whether a hub-only run should bypass the file check (`--limit` / all-targets-ephemeral), or accept the over-block as the cost of the declared "controller has dotfiles" prerequisite.
- **Finding 6 (AC6 wording)** — state the jetson substitution as an explicit AC6 deviation in `verification.md` and fix the "6 of 6" count to name the seven exercised hosts.

**Advisability of archiving now**: `dotf spec archive` is *permitted* in this state (a fresh `PASS-WITH-GAPS` review over unchanged contract files) but I would do two things first, because they are cheap and both are in artifacts the archive gate does not measure: the runbook fix (finding 2) and the one-line dispositions in `verification.md` for findings 1, 5 and 6. Findings 3 and 4 are small enough to fix in the same pass. No Blocker exists, so nothing here needs a re-review round; if any of the three contract files is edited after this review, the archive will refuse and a new review is required.
