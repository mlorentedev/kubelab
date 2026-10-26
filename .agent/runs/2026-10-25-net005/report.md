# Run report: 2026-10-25-net005

- Armed 2026-10-25T08:25Z, expires 19:25Z. Objective: implement NET-005 (#2661) PR by PR, test-first. Leave every live step that can cut `eth0`, and every change that deploys to prod, for the operator.
- Scope chosen at arming: write code and merge only the inert PRs. Live RPi4 changes, storing secret values, and the bring-up (B1 to B13) stay out.
- End reason: `budget` (envelope time), with PR 11 not started. Status below is as of the report; the handoff carries anything that changed after it.

## Merged under the standing grant

| PR | Tasks | What |
|---|---|---|
| #2664 | (found) | `chown` long-option test checks behavior, not the GNU banner |
| #2663 | PR 1 | NET-005 spec and ADR-075 |
| #2665 | PR 2, tasks 1–4 | `networking.edge` in the SSOT; edge `SecretSpec`s (values not stored: B1) |
| #2666 | PR 3, tasks 5–11 | `inet kubelab` as the forward control, sysctls, resolver, udp 67 on `eth0`. **Proven live** over the LAN (task 11, `verification.md`) |
| #2667 | PR 4, tasks 12–15 | uplink netplan rendered from the site profile; `/etc/netplan` owned by the role |
| #2677 | task 37 (lesson) | lesson-621, the CLAUDE.md gotcha, lesson-110 superseded, and ADR-075 D3 corrected: ufw governs only the part of the forward path that Docker's and Tailscale's chains did not accept, and its forward policy stays ACCEPT on the edge. Merged 16:16Z as `ae3828ba`, after four triage rounds and the second independent review |
| #2674 | PR 9, task 30 | `make edge-status`: up / portal / dead / unknown. Merged 16:57Z as `95216a4d`, after a merge of master cleared GitHub's unexplained `BLOCKED` and PR-Agent's three repeat findings were triaged |

## Open, and why

| PR | Tasks | Why it is open |
|---|---|---|
| #2670 | PR 5, tasks 16–17 | Lab AP. Blocked by the GitGuardian finding on #2103 (`0efef18b`), a false positive only the operator can dismiss. **Lands after #2668**: its regdomain check stops every rpi4 provision while the cmdline carries the token, and skips every role after `gateway` |
| #2671 | PR 6, tasks 18–21 | Collision alert and CAKE shaping. Stacked on #2670; same blocks. Out of draft at 15:50Z; PR-Agent's first review triaged |
| #2673 | PR 8, tasks 28–29 | Watchdog and radio liveness. Stacked on #2671; same blocks. Out of draft at 15:50Z. PR-Agent's and CodeRabbit's reviews of `9c43e9b5` triaged at 16:45Z; CodeRabbit's Minor applied in `fd97aee9`: the watchdog check ran after the AP's notifies, so a failure dropped them (lesson-620). The same placement was on master since #2666 (the Tailscale floor after the ruleset's notifies) and is fixed in the same commit, with `test_no_check_runs_between_a_notify_and_its_flush` guarding the role. **Until #2673 lands, master keeps that floor-check placement**; nothing provisions the edge before then |
| #2672 | PR 7, tasks 22–25 | Prod edge probe. Touches `infra/k8s/**`, which Argo CD deploys to prod; never merged unattended. **Owner decision needed (task 26):** prod already repeats a firing page every 4h until silenced. Accept 4h, add a shorter child route, or repeat from n8n |
| #2676 | PR 10, tasks 32–33 | `make headscale-rejoin` and `make edge-lan-link [ROUTE=1] [STATIC=1] [REMOVE=1]`. Was stacked on #2674; master merged in after #2674 landed (`ff14fba5`, three add/add conflicts taken from this branch). Awaiting CI and a re-review |
| #2681 | PR 12, task 35 | Runbook `lab-edge.md`, rewritten bootstrap and hardware docs. Describes #2670/#2671/#2673/#2676, so it lands after them. Draft; master merged in at 16:21Z (`7727982b`) |

## Not done

- **PR 11 (task 34, PSK rotation)**: not started, and it should wait for the bring-up, not only for time. The task chooses its design from B7: if the radio offloads the WPA handshake, the rotation takes ADR-075 D8's fallback. It also renders into the hostapd configuration of #2670, which is still blocked. Building it before B7 risks building the wrong variant.
- **Task 31 (login mode)**: built only if B3 finds that only the site's resolver answers before the login.
- **Task 36 (`always-on`)**: deferred to after B12. An always-on node enters the R2 watcher's targets, which would page while the edge is offline.
- **Task 35, `docs/troubleshooting/networking-dns.md` and `docs/runbooks/headscale-setup.md`**: they still name an adapter by its MAC, and are outside this run's write paths. They sit in a ledger in `tests/test_edge_runbook_commands.py` that may only shrink.
- **Task 37**: #2677 covers the lesson, the CLAUDE.md gotcha and lesson-110's supersession note. The remaining fix to `docs/runbooks/rpi4-sd-card-provisioning.md` is outside the write paths.
- **Task 38**: the dotfiles `rpi4-lan` alias, another repository.
- **Task 33's last sentence**, undoing the hand-made `lab-bootstrap` NetworkManager profile on the laptop, moved to B4. It is the operator's path to the edge until `make edge-lan-link` has carried a session.

## Tickets filed

- #2668 ANSIBLE-067: `rpi_boot` removes the hand-added cfg80211 regdomain from the RPi4 cmdline.
- #2669 SEC-036: separate the Authelia trust list from the private-range deny list.
- #2675 NET-007: the RPi4's hand-made `tailscale-watchdog` has its own flag list and no `--reset`.
- #2678 NET-008: Headscale approval of the edge's subnet route is a hand step.
- #2679 NET-009: nothing allowlists a captive portal's hosts in Pi-hole.
- #2680 NET-010: the `gateway` role installs packages before it renders the uplink. A fresh card at a new or captive site may not get its uplink up. Not measured on a fresh image.
- #2682 NET-011: a radio that flaps clears the reboot latch each time it serves, so only the cap bounds it, at two reboots an hour for as long as it flaps.
- #2683 NET-012: no supported way to pause the liveness ladder for maintenance. Its target name is the operator's call.
- #2684 NET-013: **the edge's failures post at `log` severity, not `page`** (below).

## Findings worth the operator's attention

- **The edge does not page today (#2684).** ADR-075 and the first runbook draft said the edge's units post `tag: page`. They fail into `kubelab-notify@`, which posts `node_notify_severity`, one value per host, and that is `log` (ratified 2026-08-15 for maintenance and backups). n8n routes `log` to the log channel. So a radio that did not come back after its reboot, which needs its power cable pulled, reaches the log channel. The three ways out are in the ticket; the runbook now says `log`, and B8's "must page" steps will fail until one is chosen.
- **rpi3 and rpi4 were offline** for most of the run; PR 3's live proof was the only host change. At 16:20Z the RPi4 still did not answer SSH over the tailnet, so the shaper's kernel modules (`sch_cake`, `ifb`, `act_mirred`, `cls_matchall`) are left to B9.
- **`NODE=rpi3` is refused by `headscale-rejoin`**: rpi3's play has no `tailscale` role.
- **bee, ace1 and ace2 mint reusable pre-auth keys** of their own. Making the edge's play always mint is the operator's call; the rejoin mints single-use, one-hour keys only when the node is off the mesh.
- **`edge-lan-link` is NetworkManager only**, so it runs on the Linux laptop. The Mac, the operator's machine from now on, has no implementation yet.
- **A fresh SD card serves no DHCP on `eth0`.** Fixed with `STATIC=1` (the last host of `networking.lan_cidr`) rather than ticketed.
- **pre-commit's ruff skips `tests/**`.** Run `ruff format`/`check` on test files by hand.
- **#2672 and #2681 both create `docs/runbooks/lab-edge.md`.** #2681 holds the stub `## Edge alerts`; the PR that lands second merges them. Both PRs carry a note.
- **#2674's `BLOCKED` cleared with a merge of master, and it landed.** Every required check had been green, it was mergeable, its reviews were triaged, and neither branch protection nor any ruleset explained the block; re-running cancelled checks had not cleared it. At 16:48Z its branch was behind master by #2677, and merging master in turned it `CLEAN` within minutes. The cause stays unexplained; the remedy that worked is a merge of the base. Landed at 16:57Z. A stale peer PR, #2656 (last updated 2026-10-23), also edits `toolkit/README.md`; the overlap was checked only after the land, and that PR may need a trivial rebase of the table.

## Reviews

Each PR got PR-Agent and, where its quota allowed, CodeRabbit. Every finding was dispositioned under `## Review triage` on its PR, with "the PR author did this triage". Codex's quota was exhausted all day.

An independent adversarial reviewer (not the implementer, read-only) went over #2670, #2671, #2673 and #2676 at about 15:00Z. Its verdicts, verbatim:

- #2670: PASS-WITH-GAPS (F2 merge order, F1)
- #2671: FAIL (red Tests, REAL)
- #2673: FAIL (inherits #2671's red Tests, plus F3)
- #2676: PASS (nothing above Minor)

What moved:

| Finding | Disposition |
|---|---|
| B1, Blocker: `test_node_notify_role.py` red on #2671/#2673; the gateway's units page through `kubelab-notify@`, and `TAGS=gateway` did not select the notifier | Fixed on #2671 (`b4d74282`): `gateway` on both `node_notify` and `node_maintenance`, as `agent_stack` on ace2. The reviewer's one-line fix would have moved the failure: the test also requires the two to share their tags |
| F3, Major: the reboot cap was a sliding window, so a dead radio rebooted the edge twice an hour forever (reviewer's simulation: 10 reboots in 200 min) | Fixed on #2673 (`222ca4bd`): the reboot marker latches until the AP serves; the cap still bounds a flapping radio. The reviewer's simulation on the new script: 1 reboot in 200 min |
| F4, Major (theoretical): `operstate=up` assumed until B10 | Bounded by F3's latch to one reboot; measured at B10. No gate |
| F1, Major (theoretical): `apt update` before checking installed packages stops a re-provision at an expired portal | Fixed on #2670 (`670d95dd`): refresh only in the rescue, then retry |
| F2, Major: #2670's regdomain check stops every rpi4 provision until #2668 | Merge-order rule: `## Lands after #2668` in #2670's body, a comment on #2668, and here. `rpi_boot` is outside this run's write paths |
| Minors: tasks 28/29 undated; a PSK reload lost if the play fails before the flush | Dated. The reload is now a requirement of task 34, which owns rotation |

**Pattern worth keeping: verification chosen by file name misses cross-cutting guards.** B1 went unseen because both PR bodies ran a selection of tests named after the change (`test_gateway_*`, `test_edge_*`), and the guard that failed lives in `test_node_notify_role.py`. Earlier in the run the same thing happened with the `ENV_TARGETS` guard. CI caught both; the PR bodies claimed green. The stack's verification is now the full suite.

**A reviewer's factual claim adopted without checking.** PR-Agent said ufw re-inserts its `FORWARD` jumps on every reload; #2677's `7acd8876` adopted it. ufw's init script (`/usr/lib/ufw/ufw-init-functions`, 0.36.2) appends them only when its chains are missing, and a reload leaves them in place. Corrected in `93925960`.

A second independent reviewer (read-only, not the implementer) re-checked the fixes at about 15:50Z: `670d95dd`, `b4d74282`, `222ca4bd`, `93925960` and `30dd4684`. Its verdicts, verbatim:

| PR | Verdict |
|---|---|
| #2670 | PASS |
| #2671 | PASS |
| #2673 | PASS-WITH-GAPS |
| #2677 | PASS-WITH-GAPS |
| #2681 | PASS-WITH-GAPS |

What moved:

| Finding | Disposition |
|---|---|
| #2677, Major (wording): "ufw governs only what the host itself accepts" overstated. The edge's own NAT falls through Docker's and Tailscale's chains to ufw's forward policy, which is why the role keeps it ACCEPT. The same overstatement was in the lesson's title, Problem and Rule and in ADR-075 D3 | Fixed in `62eecf9b` (lesson, CLAUDE.md, ADR-075 D3 with a dated note), then landed. The advisor had judged nothing overstated; the reviewer read the role's ACCEPT task as the counter-evidence, and the advisor agreed on reconcile |
| #2681, Major: the exit-code table sat under `make edge-status`, and make turns any failure into exit 2, so a dead uplink reads as a portal | Fixed in `dc59c5c1`: read the `uplink:` line; the codes are `toolkit infra edge status`'s |
| #2673, Minor: a reboot `systemctl` refused left the latch set, and the marker write was fail-safe only because dash exits on a special builtin's failed redirection | Fixed in `9c43e9b5`, test-first: the marker is written first and checked, a refused reboot clears it. 3 mutations, each red. Full suite 7086 passed |
| #2673, Minor: stale "capped per hour" prose in the unit, the test module and `verification.md`; the promised "stop the timer" operator note existed nowhere | Fixed in `9c43e9b5`; the runbook now says not to stop hostapd by hand, and the pause target is #2683 |
| #2673, Minor: a flapping radio still reboots twice an hour | Ticketed, #2682 |
| #2670, Minor: "still converges" holds only under `TAGS=gateway` | Fixed in `2299b392` (comment and body) |
| #2671, Minor: a first `TAGS=gateway` run that stops at the AP packages has no notifier yet | Declined: that run is an attended bring-up step, and `agent_stack` on ace2 has the same order |
| #2681, Minors: fresh-card-only wording, `tag: page`, exit 4 needing #2674 | Fixed in `dc59c5c1`. Checking `tag: page` found #2684 |

PR-Agent's later reviews also raised a reservations default on #2670 (fixed, `8678c60a`: the role's default is now `null` and the address check refuses it) and four findings on #2671's first review (one disproved by `test_a_success_with_nothing_failing_sends_nothing`, two deferred to B8 and B9, one declined). Each is in that PR's triage.

## After the run (interactive, 2026-10-25 evening)

The operator came back before the bring-up and kept the session going interactively, with the same merge rules. Landed under the standing grant, in this order:

| PR | Master commit | What |
|---|---|---|
| #2676 | `3636f124` | `make headscale-rejoin`, `make edge-lan-link` |
| #2686 | `75cb7961` | `rpi_boot` removes the kernel parameters a play declares absent (#2668's fix), so #2670 no longer stops every rpi4 provision |
| #2670 | `688a752e` | Lab AP. The GitGuardian block cleared |
| #2671 | `f41bec87` | Collision alert and CAKE shaping. Round 3's SSOT finding applied: the lease check's fixtures derive every lab address from `networking.*` |
| #2673 | `c884f126` | Watchdog and radio liveness |
| #2687 | `a0d04701` | rpi3's Tailscale owned by the `tailscale` role, so `make headscale-rejoin NODE=rpi3` works (#2685 closes at B6). PR-Agent's missing-role-tag finding applied, with a mutation proof |

Then, in this order:

| PR | Master commit | What |
|---|---|---|
| #2681 | `a8bdbc99` | Runbook `lab-edge.md`; the hand-written netplan doc retired (DOCS-6 in #825 ticked). Guard-the-guard tests: the runbook has commands to check and no untagged fence |

Then #2688 `14369af4` (#2684 option B; only the lease check and the liveness unit page, the shaper logs by the operator's decision; lesson-623). The operator merged it after the round-3 triage of `a53abf7e`, and #2684 closed. Filed #2690 for the unexplained `BLOCKED`.

Still open at handoff:

- **#2672** (prod probe): lands during the bring-up, after B3 and a staging validation (task 27), by the operator's decision.

**`BLOCKED` with every required check green, again.** #2687's `a6087d45` sat `BLOCKED`, mergeable, triaged, with all five required contexts green. Branch protection is `strict: false`, there are no rulesets and no unresolved threads, so "behind master" is not the explanation. A merge of master cleared it, as with #2674. The cause is still unexplained; the remedy is the same.
