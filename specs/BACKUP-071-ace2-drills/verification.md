---
tags: [spec, verification, templates]
created: "2026-10-01"
---

# Verification - BACKUP-071-ace2-drills

## Baseline on ace2 (2026-10-01, before any change)

`ssh ace2` (non-interactive): user `manu` is in `docker`; `docker`, `make`, `git` and `/usr/bin/python3` are present; `restic` and `poetry` are missing; no `~/.config/sops/age`; no `~/.local/share/kubelab-drill`. mise pins python 3.12.13 for interactive shells only, so a non-interactive ssh session sees the system python.

## Evidence

Implementation branch `feat/backup-071-ace2-drills`. Commits: `d89a5b83` (IaC), `1c3fce7a` (Headscale live split), `58dadd0b` (remote run and CLI), `66a5fcc6` (`HOST=` in Make), `26cf64c3` (runbook), `86f6d16a` (fixture scope), `9c9f763a` (BACKUP-040/067 runs), `b2e3e44d` (lesson-502).

- [x] **AC1.** `make provision NODE=ace2 ENV=prod`, second run on 2026-10-01: `ace2 : ok=162 changed=0 unreachable=0 failed=0 skipped=71`. Re-read over a non-interactive ssh on 2026-10-01:
  - `test ! -e ~/.config/sops/age/keys.txt` exits 0;
  - `restic 0.19.1` (the `backup.r2.restic_version` pin);
  - `poetry` at `/usr/local/bin/poetry`, the `dev_node_local_bin_wrapped` wrapper;
  - the dev user is in `docker`;
  - the drill checkout at `~/.local/share/kubelab-drill` is clean.

  f1's tightened gate ran green on 2026-10-01 after the merge with master (rc=0): the second provision recap matched `changed=0`, then the key probe ran. The move did not disturb the backup nodes: `make backup ENV=prod CHECK=1` on the branch reports `changed=0` on beelink, kubelab-vps, rpi3 and rpi4, through the same restic tasks (version check, download, install).

  The shared install is `infra/ansible/roles/node_backup/tasks/restic.yml`. `tests/test_restic_install_shared.py` fails if either role grows its own download, or if `dev_node` stops passing the pinned version.
- [x] **AC2.** Both drills ran on ace2 from pushed commits:
  - Headscale at `66a5fcc6`: snapshot `024a9582`, 12 nodes, 4 users, RTO 8s, rc=0.
  - Gitea at `86f6d16a`: snapshot `0b556cbb`, 5 repositories, fsck ok, 22s, rc=0. Nothing was left on ace2 (`ls /tmp | grep -c drill` = 0).

  The output carries names, ids and counts only. Refusals happen before any ssh and before inputs resolve:
  - a dirty tree (untracked files included), or a commit origin lacks: `test_a_tree_origin_cannot_reproduce_refuses_before_any_ssh` (parametrized), which also asserts the inputs are never resolved;
  - inputs that cannot be resolved send nothing: `test_inputs_that_cannot_be_resolved_send_nothing`.

  Headscale's live reads stay on the workstation: `read_live` runs there, and `run_drill(live=...)` opens no ssh (`test_run_drill_compares_against_the_given_state_and_opens_no_connection`).
- [x] **AC3.** `tests/test_drill_remote.py` (26 tests) uses sentinel secrets (`sentinel-restic-9f3a`, `sentinel-r2-id-51c0`, `sentinel-r2-secret-7d2e`, `sentinel-gitea-token-c48b`):
  - none of them appears in the ssh argv;
  - the payload travels on stdin;
  - every setup step reads `/dev/null`, so only the drill sees the payload;
  - the entrypoint runs with `ConfigurationManager` patched to raise;
  - no file under the work directory holds a sentinel at teardown (`rmtree` is wrapped to inspect before it removes);
  - a malformed payload fails naming only the exception class.

  Scope limit: the entrypoint test proves the drill path builds no `ConfigurationManager`. It cannot prove the toolkit import does none, because `toolkit/config/settings.py` builds one at import time (#2021, lesson-502). On ace2 that import found no `sops` binary and no key, so nothing was decrypted there.
- [x] **AC4.** `specs/BACKUP-040-gitea-restore-drill/verification.md` ("AC1, AC2: the prod drill on ace2") and `specs/BACKUP-067-headscale-restore-drill/verification.md` ("Prod run, 2026-10-01, on ace2 (BACKUP-071)") record host, commit, snapshot and result (`9c9f763a`).
- [x] **AC5.** `docs/runbooks/offsite-backup-restore.md`, section "Running a drill on ace2" (`26cf64c3`). It covers `HOST=ace2`, push first, and what travels to ace2 (stdin payload) and what does not (SOPS, the VPS credential, a forwarded agent).

## Test status

- Round 1 fixes: `tests/test_drill_remote.py tests/test_headscale_drill.py tests/test_gitea_drill.py tests/test_restic_install_shared.py tests/test_node_backup_role.py`: 140 passed.
- `make test` on `b2e3e44d`: `3435 passed, 16 skipped, 154 deselected, 2 xfailed`, rc=0.
- `make test` on `1cb1538d` (round-2 code, before the archive): `3481 passed, 16 skipped, 154 deselected, 2 xfailed`, rc=0.
- Mutations, each committed first and restored with `git checkout HEAD --`. Each one turns the suite red:
  - M1, a setup step reads stdin: 1 failure;
  - M2, a malformed payload is echoed: 3 failures;
  - M3, a dirty tree is accepted: 2 failures;
  - M4, ssh failure is not classed: 1 failure.
- Round 1 mutations, same discipline. Each turns the suites red with 1 failure:
  - M5: `apt: name=restic` added to `drill_runtime.yml`;
  - M6: an `unarchive` of a restic asset;
  - M7: a `shell` that pipes `curl` into `/usr/local/bin/restic`;
  - M8: the `networking` read moved back outside the guard.
- Round 2 mutations, same discipline. Each turns the new Gitea test red with 1 failure:
  - M9: the drill writes `restic_env` into its workdir. The root wipe erases it before `rmtree` runs, so only the wipe-time scan catches it;
  - M9b: `run_from_inputs` stops passing `run=_default_run`, so the real `restic` runs and the drill fails.
- No regressions. Without `HOST`, the local drills keep today's behaviour, and `tests/test_headscale_drill.py` (40) is green.

## Decisions made during implementation

- **Headscale live reads stay on the workstation.** `read_live` runs before the payload is built, so ace2 never holds a VPS ssh credential or a forwarded agent. The live state crosses as data (`LiveState.to_payload`).
- **ace2 runs the commit this tree is at, not master.** That is why a dirty or unpushed tree refuses: otherwise the evidence would vouch for code the host never ran.
- **Exit classes.** 255 is ssh, 97 is setup and anything else is the drill's own verdict. Each failure is labelled CANNOT CHECK or "did not pass" accordingly.
- **No traceback locals.** `pretty_exceptions_show_locals=False` on the Typer app, because a traceback rendering locals would print the payload.

## Adversarial review dispositions (round 1, FAIL)

`dotf spec review` (nan/deepseek-v4-flash) at `bd3bec16`: FAIL on two REAL Majors. Each is applied below, and a re-review follows.

| # | Finding | Disposition |
|---|---|---|
| 1 | Major: AC3 and proposal §2 claim the remote process builds no `ConfigurationManager`; importing the toolkit builds one for `dev` (`settings.py:419`) | **Contract reworded, gate added.** Making the global lazy is #2021's work: 27 modules import `settings` at module level, `k8s_connect` (which `ssh_target` uses), `main` and `logging` among them, so it is a toolkit-wide change, not a drill change. AC3 and §2 now claim what the test proves (the drill path builds none). The guarantee that ace2 decrypts nothing now rests on a gate, not an observation: f1 asserts no age key **and** no `sops` on the non-interactive PATH (`! command -v sops`, rc=1 on 2026-10-01) |
| 2 | Major: the AC1 gate only sees `get_url` | **Applied.** `_acquires_restic` checks acquisition modules: `apt`/`package`/`dnf`/`yum`/`snap`/`pip` names; `get_url` url; `unarchive`/`copy` src, or a dest that is the binary; `shell`/`command`/`raw` text naming restic with a fetch or unpack tool. It matches by module, so `import_tasks: restic.yml`, `restic version` and the password file do not count. The reviewer's two mutations (an `apt: name=restic` and an `unarchive` of a restic asset in `drill_runtime.yml`) each turn it red |
| 3 | Minor: the CLI calls the private `drill_remote._module` | **Applied.** Renamed `module_for`, the reviewer's name, public with a docstring |
| 4 | Minor: a config with no `networking` is a `KeyError` traceback | **Applied.** The read moved inside the existing guard, and the message names `networking.nodes.<host>`. `test_a_host_the_config_cannot_place_is_cannot_check` covers both no-networking and an undeclared host |
| 5 | Question: a stale `origin/*` refuses a pushed commit | **Applied (runbook).** The section says the check reads local remote-tracking refs, and to `git fetch origin` and rerun. Network I/O in preflight was not added: it would run before the refusal it exists to make cheap |
| 6 | Minor, SPECULATIVE: formatting-only lines in `dev_node/tasks/main.yml` | **Declined.** Produced by the pre-commit formatter on a file this change edits. Harmless, and reverting them would fail the hook |

## Adversarial review dispositions (round 2, PASS-WITH-GAPS)

`dotf spec review` (nan/deepseek-v4-flash) at `ef241218`: PASS-WITH-GAPS, no REAL Major. The contract set (proposal, tasks, `features.json`) is closed under this verdict, so every change below is in code, tests or this file.

| # | Finding | Disposition |
|---|---|---|
| 1 | Major, THEORETICAL: the no-secret-on-disk half of AC3 is tested for Headscale only | **Applied.** `test_a_real_gitea_restore_on_the_host_writes_no_injected_value_to_disk` runs `drill-gitea --inputs-stdin` with sentinel restic credentials and token against the Gitea fake. It reads every file the drill wrote at the root-run wipe **and** at `rmtree`: the wipe empties the tree first, so a scan at `rmtree` alone would see nothing. For the patch to reach the drill, `run_from_inputs` now passes `run=_default_run` explicitly, as Headscale's does; a default bound at definition time ignores a later monkeypatch. Mutations M9 and M9b below turn it red |
| 2 | Minor, REAL: `preflight` diagnoses a stale `origin/*` as unpushed | **Applied.** The refusal reads "no origin/* branch here contains `<sha>`; push it, or `git fetch origin` if these refs are stale". The `unpushed` case asserts the fetch hint |
| 3 | Minor, THEORETICAL: one `except KeyError` covers the config read and `ssh_target` | **Applied.** Two guards: a config with no `networking` says "the `<env>` config declares no networking block", and an undeclared node says `networking.nodes.<host>`. The parametrized test asserts each message for its own case |
| 4 | Minor, SPECULATIVE: exit 97/255 could be the drill's own status | **Declined.** `drill-<x> --inputs-stdin` exits only 0 or 1 (`typer.Exit(code=1)`, and an uncaught exception is 1), so neither value is reachable from the drill. Only ssh produces 255 and only the setup lines produce 97 |
| 5 | Minor, REAL: the f4 gate (`grep -q 'HOST=ace2'`) cannot see the section's explanation | **Accepted, no ticket.** `features.json` gates run once, at archive time; neither CI nor `spec-gate.yml` re-runs an archived spec's gates. AC5's evidence is the runbook section itself, read in this PR's diff. Tightening a gate that never runs again would protect nothing |
| Q | `sops` absence is gate-only, not asserted by provisioning | **Accepted.** The load-bearing half is the age key, which `drill_runtime.yml` asserts on every provision: without a key, `sops` decrypts nothing. ace2 is a developer node (ADR-058), and a role may install `sops` there for other work. f1 measured the non-interactive PATH the drill uses on 2026-10-01 |

## Spec review dispositions (#2017)

PR-Agent on the spec PR found two `features.json` gates that could not fail. Both are fixed here:

- **f1** never ran provisioning, and its key probe passed on the baseline. It now runs `make provision NODE=ace2 ENV=prod`, requires the recap `ace2 : ... changed=0 ... failed=0`, and only then probes for the key.
- **f5** matched any mention of `HOST=ace2`. It now requires, in each verification file, the drill's `running <x> on <target> at <12-hex>` line, a `snapshot <8-hex>` line and `rc=0`. A file holding only a pending mention fails it (checked, rc=1).

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/toolkit-tooling/lesson-502-a-patch-applied-after-import-cannot-see-what-the-import-did.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: the operator's decision (no age key on ace2, secrets per run) is recorded in the spec and issue #2011; it changes no standing architecture.
- [x] New pattern candidate for `00_meta/patterns/`? no: one project, one occurrence.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/BACKUP-071-ace2-drills/` -> `specs/archive/BACKUP-071-ace2-drills/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
