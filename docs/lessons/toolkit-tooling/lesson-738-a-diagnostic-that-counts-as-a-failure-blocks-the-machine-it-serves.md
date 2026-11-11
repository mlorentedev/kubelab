---
id: lesson-738-a-diagnostic-that-counts-as-a-failure-blocks-the-machine-it-serves
type: lesson
status: active
created: "2026-11-08"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, bootstrap, ansible]
---

# A diagnostic that increments the failure counter becomes a verdict, and the installer blocks the only machine it was built for

**Context**: bringing up a fresh Ansible control node from WSL, the documented
path is `scripts/bootstrap-controller.sh`, whose whole purpose is "install what
is missing here, then hand off to `make setup-ansible`".

**Problem**: the script reported `[FAIL] make is not installed`, installed it,
printed `[ok] GNU Make 4.3`, reported `[FAIL] poetry is not installed`, installed
it, printed `[ok] poetry 2.5.1`, and then refused:

```
[ERROR] 2 prerequisite(s) above are unresolved; not handing off to make
```

`bad()` incremented `FAILED` and `ok()` never decremented it, so the
*pre-install diagnosis* was counted as a *post-install failure*. `grep FAILED`
found zero decrements anywhere. The script could never reach its hand-off on any
machine to which it had just installed something — that is, on every machine
that needs it, and on no other. On a host that already had both tools it worked,
which is why it had never been caught.

Two secondary defects surfaced in the same run, both of the same shape — a check
that reports on itself rather than on the thing it is meant to measure:

- `sudo` was invoked without `-n`. `sudo` reads its password from `/dev/tty`,
  not stdin, so `</dev/null` gives `sudo: unable to read password: Input/output
  error` (and `set -e` aborts with no message) while a reachable `/dev/tty`
  simply **blocks** (measured: process alive 123 s with no output).
- `apt-get update -qq` returns rc=0 even when it cannot open the dpkg lock, so it
  cannot be the gate. The gate has to be `have_gnu_make` after the install.

**Solution**: separate the diagnosis from the verdict. `bad()` now fires only
where there is no recovery left — in `--check`, or after an install attempt has
actually failed. The pre-install state is reported with a new `note()`, which
prints the same `[note]` line without touching `FAILED`. Privilege is probed
once, up front, with `can_root()` (`id -u` or `sudo -n true`) and every root
command goes through `as_root`, which is `sudo -n` by construction.
`tests/test_bootstrap_controller_script.py` pins all of it against stubbed
`make`/`poetry`/`apt-get`/`sudo` on an isolated PATH.

**Rule**: a counter that mixes "what is wrong now" with "what was wrong before
the fix" can only ever answer "something was wrong once". Decide *where* the
verdict is emitted, not *how many* problems there are: emit `bad` only at a point
of no return, and report everything recoverable as a note. The same rule applies
to every privileged call — probe privilege non-interactively first (`sudo -n`),
because a prompt is not a failure, it is a hang, and a hang has no exit code.

**Tags**: `#bootstrap` `#sudo` `#testing` `#3234`
