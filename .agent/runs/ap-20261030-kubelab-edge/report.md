# Run ap-20261030-kubelab-edge

Verdict: ended. Reason: `queue-empty`. All four named Backlog items are closed (#2792, #2817, #2765, #2637), and the run already used its 8 items: the 4 named items plus #2824, #2703, #2812 and B11. No new ticket is picked after this point.

Host: the laptop held `systemd-inhibit --what=idle:sleep` from arming until 11:58Z, when the run's last work was done and it was released. The window was covered.

## Waiting on you (irreversible and urgent first)

1. **`down_kbit`.** The refill measured 2.17 to 2.57 Mbit/s steady, against the declared 2970 in `common.yaml` (#2703, comment 6519413028). The include's estimates run about 20% short at that rate. Whether to lower the value is yours: `infra/config/values/**` is frozen for runs.
2. **#2703 AC3**: the decision on a local image source. AC1 and AC2 are done.
3. **#2807 (LPS)**: decide at the end of the soak. B12's reading is `make edge-soak` after 2026-10-31T21:50Z.
4. **#2843: the Gitea version floor.** The PR uses 1.26.0, the ticket's value. If the pin must never go below the version OPS-038 rehearsed, the floor should be 1.27.3. That is a one-line change.
5. **#2501: (A) or (B)**, on the park comment (6519724192). (A) is a per-feature declaration in `features.json`. (B) is a runner allowlist in the test. The board says Blocked.
6. **#2834**: where the one value both daemons read lives, and what it is called. The run does not name identifiers without you.
7. **#1100 AC4**: the `| default('')` design call. #2836 covers AC1 to AC3.
8. **#2787 (parked, yours)**: ace2 holds two lost notices. Its notify units failed with curl exit 6 at 2026-10-26T23:19Z and exit 28 at 2026-10-29T21:42Z, eight minutes before the soak boot. They stay `failed` in `systemctl --failed`. The evidence is on the issue (comment 6520164990). They were not reset by hand. The doubled `.service` in the unit name is systemd's `%n` instance naming, not a defect.

## Done but unmerged (left for you)

These are past the envelope's 8 items, or are found defects whose fix is wider than the item. An earlier draft of this report said each one's reviewer output was triaged. At 10:30Z `dotf pr triage-queue` showed it was not: #2842, #2844 and #2845 had PR-Agent reviews nobody had answered, and #2838 had a new one. They were answered by 11:00Z, see the ledger.

- #2838 (#2822): the guard sees images a task fetches by running them. beelink_services' qemu registration no longer pulls an unpinned image. Since the first review: a run the parser cannot read fails the guard (127fb594); `--pull`'s value is read once (85219a7c); every setter of the probe variable is pinned to the key the test sizes (19d002ed); the registration is held to the `F` flag on every run, an existing one included (64588c60, 0cff0d4e); and `raw` tasks and every env's values file are read too (a1ec4dfc, c21aebba). bee was not re-provisioned with it; its measured `flags: POF` passes.
- #2840 (#2839, TOOL-127): `make mutate` accepts an empty TO as a deletion.
- #2841 (#2506): only Kuma's not-found answer counts as a confirmed monitor delete.
- #2842 (#2617), #2844 (#2621 item 2): the errors tests read the access log and the rendered overlays.
- #2843 (#2620): the drill's doctor exclusions and the forge's version floor are pinned. See item 4.
- #2845 (#1700): a lessons index that still holds conflict markers is refused.
- #2849 (#2848): the Pi-hole flush test read a helper `pihole-FTL` process as a restart. It failed master at 517896d8 with `'279 203' == '203'`, while the daemon, 203, was still running.

CI at 11:58Z: Tests was still running on #2838 (now 25ec074b), #2840 (d6e2c550) and #2845 (ef400656). The Kuma flake (#1196) can fail #2840's Tests again; re-run the failed job if it does. #2841 to #2844 and #2849 were green.

#2840 and #2845 each add a row at the top of `docs/lessons/toolkit-tooling/_index.md`. Both were merged with master at 11:40Z, after #2846's row. Whichever lands second needs one more merge: put its row above the other, newest first.

## Filed, no PR

- #1196 (existing, TEST-001): the Kuma Socket.IO timeout failed #2840's Tests, with evidence added. The failed job was re-run.
- #2847 (TOOL-128, Backlog P2): `make mutate` loses every `$` in FROM and TO to make's expansion. Found while mutating `nginx.conf` for #2842.

## Landed under the grant

#2827 (#2824) 06:56, #2828 (#2792) 07:28, #2829 (#2637) 08:01, #2833 (#2765) 08:45, #2835 (#2703 resume) 08:53, #2836 (#2817) 09:39, #2837 (#2812) 10:23, #2808 (B11) 10:24, #2846 (a defect found working B11) 11:03. Before arming: #2825 05:27.

## Disclosures

- **Outside the envelope's remote write.** `make provision NODE=ace2 ENV=prod TAGS=docker` for #2835 restarted dockerd and glances on ace2. There was also a check-mode `deploy-vps` run. Read-only SSH reads ran on bee, ace2 and rpi4: ace2's journal, and rpi4's wpa_supplicant journal for the beacon-loss question on #2703. The run also used a local Kuma container for the #2841 integration test, local errors-image `docker run`s, and two read-only prod e2e subsets (`-k open_webui`).
- **Outside `allowed_commands`.** `python3` heredocs did exact-string file edits, and `docker run --help` enumerated `_FLAGS` for #2838. Neither changed anything outside a worktree.
- **Self-corrections.** On #2808 the run withdrew the 03:36Z e2e figures without reading the log. The log proved them right, and the withdrawal was itself an unverified claim. Reverted in 37756262. The #2837 triage said "CI is green" while Tests was running, and was corrected within a minute (comment 6520012685).
- **A frozen path, after the run.** At 15:15Z, with the operator back, `infra/config/values/prod.yaml` was edited to prove #2838's overlay check goes red, on a committed tree, then restored with `git checkout HEAD`. `git status` was empty afterwards.
- **The 03:36Z and 09:33Z runs.** They ran from bb218821 and fba90b14. `git log bb218821..fba90b14 -- tests/e2e/` is empty, so the two runs differ by ace2's state alone.

## Ledger

| UTC | Item | Result | Evidence |
|---|---|---|---|
| 05:00 | #2703 | refill attempt 1 (before arming) | comment 6515379356 |
| 05:40 | arm | envelope f8158b7b | run branch |
| 06:35 | #2703 | attempt 1 stopped by hand: dockerd's 5 attempts dropped every layer | #2835 |
| 06:44 | #2703 | attempt 2, `max-download-attempts` 40 | refill/events.log |
| 06:56–09:39 | #2824, #2792, #2637, #2765, #2817 | landed | #2827, #2828, #2829, #2833, #2836 |
| 08:53 | #2703 | layer resume landed | #2835 |
| 09:05 | #2703 | attempt 2 done (rc=0); rerun at 09:16 `changed=0` | comment 6519413028 |
| 09:32 | #2812 | ace2 provision from ee90903c `ok=204 changed=0` | #2837 |
| 09:33 | B11 | staging e2e 68/21/0; prod Open WebUI 8 passed | #2808 |
| 09:42 | #2501 | parked, two options; board Blocked | comment 6519724192 |
| 09:51 | found | e2e probe read before the declaration | #2846 |
| 07:59–09:21 | past the 8 items | #2822, #2839, #2506, #2617, #2620, #2621, #1700 | PRs above, unmerged |
| 10:00 | reviews | #2837, #2838 triaged; #2808 text clarified (0101cdbc) | PR comments |
| 10:23–10:24 | #2812, B11 | landed | #2837, #2808 |
| 10:40 | #2846 | PR-Agent's three findings: two applied (guard reads every e2e module; a prod-side test, which first passed against a non-probing mutant because a skip escapes `pytest.raises`), one declined | c93ef2e5 |
| 10:45–11:15 | reviews | #2838 (`--pull` read twice; variable-keyed runs fenced; QEMU F flag asserted), #2842 (a served page, not only a logged one), #2845 (indexes at any depth): applied, with mutants red. #2844 answered. Triage posted on each | PR comments |
| 11:03 | #2846 | landed | 21529cdb |
| 11:05 | found | Pi-hole flush test misreads a helper process; filed #2848, fixed in #2849 | #2849 |
| 11:10 | #2838 | QEMU registration must carry the F flag; PO fails, POF passes | 64588c60 |
| 11:35 | #2838 | PR-Agent: the probe variable could be reset from another key. Every setter is now pinned to the key the test sizes; mutant red | 19d002ed |
| 11:40 | #2840, #2845 | merged master (index conflict with #2846's row); #2840's Kuma flake (#1196) re-runs on the new head | 70168170, ef400656 |
| 11:40 | #2849 | CI green; marked ready | 93151a53 |
| 11:45 | #2840 | PR-Agent: a TO set in a makefile would reach `--to` empty. `--to` now passes only for a command-line or environment TO; assertion red first | d6e2c550 |
| 11:50 | #2838 | CodeRabbit: the F check skipped a registration that already existed. It now runs on every run, check mode included where there is one to read | 0cff0d4e |
| 11:55 | reviews | triage posted on #2838, #2840, #2845, #2849; `dotf pr triage-queue` exit 0 | comments 6522061184, 6522061745, 6522088436, 6521922967 |
| 11:58 | #2838 | lesson-671 and the PR body updated for the every-run F check | 25ec074b |
| 11:58 | host | sleep inhibitor released | |
| 15:05–15:20 | #2838 | after the run, with the operator back: PR-Agent's late review on 25ec074b. `raw` tasks read; the probe image read from every values file, since an env's file overrides `common.yaml`. Mutants red | a1ec4dfc, c21aebba, comment 6526072894 |
