---
id: "TOOL-134-bootstrap-controller-verdict"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-11-08"
issue: "kubelab#3234"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
owner: manu
---

# TOOL-134: Bootstrap controller verdict

> **Naming**: file lives at `<repo>/specs/<feature-id>/proposal.md`. `<feature-id>` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

<!-- from issue #3234: bootstrap-controller.sh refuses to hand off after installing what it reported missing, and blocks on a passworded sudo -->

## Why

`scripts/bootstrap-controller.sh` exists for exactly one machine: the one that does not
yet have `make` and Poetry. On that machine it cannot succeed. Every missing tool is
reported through `bad`, which increments `FAILED`; the successful install that follows
reports `ok`, which does not decrement it. By the time the hand-off is evaluated,
`FAILED` equals the number of things that were *missing at the start* — 2 on a stock
WSL Ubuntu 24.04 image — so the script installs everything it just reported missing and
then refuses to continue, exiting 1 before `make setup-ansible`. The only machines where
it "works" are the ones that never needed it. Measured 2026-11-08: `[ok] GNU Make 4.3`,
`[ok] poetry 2.5.1`, then `[ERROR] 2 prerequisite(s) above are unresolved`.

The second defect makes the same run hang rather than fail. `as_root()` calls `sudo` with
no `-n`, and `sudo` reads its password from `/dev/tty`, not stdin: when the script is not
attached to a foreground terminal it blocks with no output (measured: PID alive at 123 s).
`--check` models the privilege question nowhere, so it reports "would install: make" on a
machine where the install would in fact prompt — the diagnostic says the machine can be a
controller and the run that follows never returns.

## What

The script's verdict becomes a statement about the machine's state **after** its own
attempts, not a tally of what it found **before** them.

- A prerequisite that was missing and was installed successfully ends the run resolved:
  the hand-off to `make setup-ansible` runs and the script exits 0.
- A prerequisite that is still unresolved after the attempt — install failed, no package
  manager, wrong version still present — is the only thing that blocks the hand-off, and
  the message counts those.
- `--check` reports whether root is actually obtainable without a password, and says so
  instead of promising an install it could not perform.
- No code path waits on a password prompt. `as_root` uses `sudo -n`; when root is not
  available the script names the remedy (`sudo -v`) and exits non-zero rather than hanging.
- A failed `apt-get update` is visible rather than swallowed by `-qq`.

## Out of scope

- **Integrity of the Poetry installer.** `curl … | python3 -` fetches a moving script from
  a CDN with no checksum, which is a real asymmetry against the rest of the repo
  (collections pinned in `requirements.yml`, Traefik plugins by sha256, images by digest).
  Replacing the installer with a hash-verified fetch is its own change and its own ticket;
  bundling it here would put two unrelated mechanisms in one review.
- **A SOPS/age preflight.** On the same WSL host the doctor reports 4/4 SUCCESS while
  `common.enc.yaml` and `dev.enc.yaml` cannot be decrypted at all (`identity did not match
  any of the recipients`). The doctor is the authority on the ansible question and its four
  checks do not include secret access; teaching it that is a separate change.
- Making the script install anything a fleet host needs. It never contacts a host.
- Windows shells: the `MINGW*|MSYS*|CYGWIN*` refusal already covers that case and is correct.

## Risks / open questions

- **Counter removal is a behavior change in `--check` too.** The pre-install `bad` is the
  only thing that currently makes `--check` exit 1 for a missing `make`, so the restructure
  must keep that: `bad` fires in `--check` (no install is attempted) and only fires in
  install mode when the attempt failed. `tests/test_bootstrap_controller_script.py`
  currently accepts `returncode in (0, 1)` for `--check`, so it will not catch a regression
  here on its own — the new test must assert the exit code explicitly.
- **`sudo -n true` is a probe, not a guarantee.** It succeeds while the cached credential
  is alive (15 min default) and fails once it expires; the script can be wrong about a
  long run. Accepted: the window is longer than this script takes, and the alternative is
  prompting, which is the bug being fixed.
- **`apt-get update` exit code.** `-qq` was measured returning 0 while printing
  "Could not open lock file … Permission denied". Whether that is `-qq` or the outer
  invocation is unverified; the fix removes `-qq` so the failure is legible, and the real
  gate stays the post-install `have_gnu_make` check that already exists.

## Acceptance criteria

- [ ] A machine missing `make` and Poetry, where both installs succeed, reaches the
      hand-off: `make setup-ansible` runs and the script exits 0.
- [ ] A prerequisite that fails to install still blocks the hand-off, and the message
      counts only the unresolved ones.
- [ ] `--check` on a host where `sudo` requires a password reports that root is
      unavailable and exits 1, without attempting an install.
- [ ] No path in the script can block on a password prompt: `as_root` never invokes `sudo`
      without `-n`.
- [ ] `apt-get update` runs without `-qq`, so a lock/permission failure is visible.

## References

- Bitácora board: [kubelab#3234](https://github.com/mlorentedev/kubelab/issues/3234) (Project #1, TOOL-134)
- Script: `scripts/bootstrap-controller.sh`
- Contract under test: `tests/test_bootstrap_controller_script.py`
- Runbook: `docs/runbooks/ansible-controller.md` — its install path is marked "Not yet measured"; this change is what makes it measurable.
