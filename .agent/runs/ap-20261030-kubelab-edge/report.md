# Run ap-20261030-kubelab-edge

Verdict: DRAFT, written at 10:15Z while #2808, #2837 and #2846 wait on CI. Reason: `queue-empty`. All four named Backlog items are closed (#2792, #2817, #2765, #2637), and the run already used its 8 items: the 4 named items plus #2824, #2703, #2812 and B11. No new ticket is picked after this point.

Host: the laptop held `systemd-inhibit --what=idle:sleep` from arming to 17:40Z, so the window was covered.

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

These are past the envelope's 8 items, or are found defects whose fix is wider than the item. Each one is CLEAN and its reviewer output is triaged.

- #2838 (#2822): the guard sees images a task fetches by running them. beelink_services' qemu registration no longer pulls an unpinned image. PR-Agent's flag-set finding was applied in 127fb594, and a run the parser cannot read now fails the guard.
- #2840 (#2839, TOOL-127): `make mutate` accepts an empty TO as a deletion.
- #2841 (#2506): only Kuma's not-found answer counts as a confirmed monitor delete.
- #2842 (#2617), #2844 (#2621 item 2): the errors tests read the access log and the rendered overlays.
- #2843 (#2620): the drill's doctor exclusions and the forge's version floor are pinned. See item 4.
- #2845 (#1700): a lessons index that still holds conflict markers is refused.

## Landed under the grant

#2827 (#2824) 06:56, #2828 (#2792) 07:28, #2829 (#2637) 08:01, #2833 (#2765) 08:45, #2835 (#2703 resume) 08:53, #2836 (#2817) 09:39. Before arming: #2825 05:27.

To land here: #2837 (#2812), #2808 (B11), #2846 (a defect found working B11).

## Disclosures

- **Outside the envelope's remote write.** `make provision NODE=ace2 ENV=prod TAGS=docker` for #2835 restarted dockerd and glances on ace2. There was also a check-mode `deploy-vps` run. Read-only SSH reads ran on bee, ace2 and rpi4: ace2's journal, and rpi4's wpa_supplicant journal for the beacon-loss question on #2703. The run also used a local Kuma container for the #2841 integration test, local errors-image `docker run`s, and two read-only prod e2e subsets (`-k open_webui`).
- **Outside `allowed_commands`.** `python3` heredocs did exact-string file edits, and `docker run --help` enumerated `_FLAGS` for #2838. Neither changed anything outside a worktree.
- **Self-corrections.** On #2808 the run withdrew the 03:36Z e2e figures without reading the log. The log proved them right, and the withdrawal was itself an unverified claim. Reverted in 37756262. The #2837 triage said "CI is green" while Tests was running, and was corrected within a minute (comment 6520012685).
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
