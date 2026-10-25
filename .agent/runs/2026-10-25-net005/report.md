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

## Open, and why

| PR | Tasks | Why it is open |
|---|---|---|
| #2670 | PR 5, tasks 16–17 | Lab AP. Blocked by the GitGuardian finding on #2103 (`0efef18b`), a false positive only the operator can dismiss. Inert, so it can land once that clears |
| #2671 | PR 6, tasks 18–21 | Collision page and CAKE shaping. Stacked on #2670; same block |
| #2673 | PR 8, tasks 28–29 | Watchdog and radio liveness. Stacked on #2670; same block |
| #2672 | PR 7, tasks 22–25 | Prod edge probe. Touches `infra/k8s/**`, which Argo CD deploys to prod; never merged unattended. **Owner decision needed (task 26):** prod already repeats a firing page every 4h until silenced. Accept 4h, add a shorter child route, or repeat from n8n |
| #2674 | PR 9, task 30 | `make edge-status`: up / portal / dead / unknown. Green and triaged, but GitHub reads `BLOCKED` with no reason given (below) |
| #2676 | PR 10, tasks 32–33 | `make headscale-rejoin` and `make edge-lan-link [ROUTE=1] [STATIC=1] [REMOVE=1]`. Stacked on #2674 |
| #2677 | task 37 (lesson) | lesson-621: ufw does not govern forwarded traffic. Awaiting PR-Agent |
| #2681 | PR 12, task 35 | Runbook `lab-edge.md`, rewritten bootstrap and hardware docs. Describes #2670/#2671/#2673/#2676, so it lands after them |

## Not done

- **PR 11 (task 34, PSK rotation)**: not started; it did not fit in the window.
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

## Findings worth the operator's attention

- **rpi3 and rpi4 were offline** for most of the run; PR 3's live proof was the only host change.
- **`NODE=rpi3` is refused by `headscale-rejoin`**: rpi3's play has no `tailscale` role.
- **bee, ace1 and ace2 mint reusable pre-auth keys** of their own. Making the edge's play always mint is the operator's call; the rejoin mints single-use, one-hour keys only when the node is off the mesh.
- **`edge-lan-link` is NetworkManager only**, so it runs on the Linux laptop. The Mac, the operator's machine from now on, has no implementation yet.
- **A fresh SD card serves no DHCP on `eth0`.** Fixed with `STATIC=1` (the last host of `networking.lan_cidr`) rather than ticketed.
- **pre-commit's ruff skips `tests/**`.** Run `ruff format`/`check` on test files by hand.
- **#2672 and #2681 both create `docs/runbooks/lab-edge.md`.** #2681 holds the stub `## Edge alerts`; the PR that lands second merges them. Both PRs carry a note.
- **#2674 is parked at `BLOCKED` with nothing to fix on our side.** Every required check is green: `Validate`, `Tests`, `Detect Changes`, `deploy-shape` (neutral) and the `review-attestation` status. It is mergeable, not behind master, and its reviews are triaged (`dotf pr triage-queue --pr 2674` exits 0). Its required contexts are identical to those of #2672, which reads `CLEAN`. GitHub's merge box names no reason. Re-running the two cancelled runs on its head (`Spec Gate`, `review-attestation`) changed nothing. `dotf pr land` refuses on `BLOCKED`, and a by-hand merge would route around that refusal, so it is left for the operator. One click in the UI shows GitHub's reason.

## Reviews

Each PR got PR-Agent and, where its quota allowed, CodeRabbit. Every finding was dispositioned under `## Review triage` on its PR, with "the PR author did this triage". Codex's quota was exhausted all day. An independent reviewer pass over #2670, #2671, #2673 and #2676 ran at the end; its result is in the handoff.
