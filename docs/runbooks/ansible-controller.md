---
id: ansible-controller
type: runbook
status: active
created: "2026-11-08"
owner: manu
---

# Choose and set up an Ansible controller

> What machine may drive `infra/ansible`, how to make it able to, and how to tell
> in four offline checks whether it is. Written because `make setup-ansible`
> reported success on a machine that could not run Ansible at all (TOOL-131,
> #3202).

## TL;DR

| Question | Answer |
|---|---|
| Can a Windows box be the controller? | **No.** `ansible-core` refuses it at import. |
| What may? | Any Linux/WSL host with **GNU make** and **Poetry**. |
| Set it up | `make setup-ansible` |
| Check it without installing anything | `make check-ansible` |
| Check it without `make` (bare WSL) | `poetry run toolkit infra ansible doctor` |

## The constraint: `ansible-core` has no Windows controller

Every `ansible-*` entry point calls `check_blocking_io()` at import, which calls
`os.get_blocking()`, which does not exist in the sense it needs on Windows.
Measured on `ansible-core` 2.21.6:

```
$ poetry run ansible-playbook --version
  File "...\ansible\cli\__init__.py", line 54, in <module>
    check_blocking_io()
  File "...\ansible\cli\__init__.py", line 46, in check_blocking_io
    if not os.get_blocking(fd):
OSError: [WinError 87] The parameter is incorrect
```

It fails at **import**, so it is not one subcommand or one flag: `ansible-playbook`,
`ansible-galaxy`, `ansible-inventory` and the rest all die the same way. A
Windows seat cannot be a controller under any configuration, and no amount of
`make setup-ansible` changes that — which is exactly why the target must fail
loudly there instead of printing `skipping` and exiting 0.

`toolkit infra ansible doctor` detects this case (`sys.platform == "win32"`) and
prints a different fix than it would for a broken install:

```
FIX: run this from WSL or a Linux host; ansible-core has no Windows controller
```

## Seat vs disposable runner

Two valid shapes. Pick by whether you intend to keep the state.

| Shape | Where | When |
|---|---|---|
| **Seat** | `msi` (Windows) + a WSL distro | interactive work; the WSL side is the controller |
| **Runner** | a throwaway Linux checkout | one-shot verification, e.g. proving a `--check` diff before a host window |

The seat's WSL side and a runner behave identically as far as Ansible is
concerned; the difference is that a runner is deleted afterwards. Neither
touches the fleet until a host window is agreed — the doctor makes **no network
call and no SSH**, so it is safe to run before any window exists.

## Setup

```bash
make setup-ansible
```

That target does three things, in order, and the third is what makes it a gate
rather than a report:

1. `poetry install --with ansible --no-interaction --no-ansi` — installs
   `ansible-core` into **this project's venv**. Not a system-wide Ansible:
   `toolkit infra ansible run` shells out to `ansible-playbook`, and
   `poetry run toolkit` puts that venv's `bin` on the `PATH`, so that is where
   it resolves from. A system-wide copy works until the two disagree on version.
2. `poetry run ansible-galaxy collection install -r infra/ansible/requirements.yml`
   — the pins are exact by design (ANSIBLE-070, #2735). With floors,
   `collection install -r` is a no-op when the installed version already
   satisfies the range, and a controller once sat one release behind a
   privilege-escalation fix in `authorized_key`.
3. `toolkit infra ansible doctor` — fails the target if the result cannot run.

To check an existing controller without installing anything:

```bash
make check-ansible            # same doctor, no install, no host contact
```

`make provision` and `make deploy` both depend on it, so the two targets that
shell out to `ansible-playbook` refuse to start on a controller that cannot run
it — the failure arrives with a reason instead of as a role-parse error three
roles into a play, which reads as a broken playbook.

## The four checks

`toolkit infra ansible doctor` (`toolkit/features/ansible_doctor.py`) runs four
local checks. Green looks like:

```
✓ ansible-core: ansible-core 2.21.6
✓ galaxy collections: 3 collections at the pinned versions
✓ ansible.cfg: infra/ansible/ansible.cfg is in effect
✓ static inventory: 7 hosts under `all`
All 4 checks passed — this machine can run Ansible
```

| Check | What it proves | Why it is here |
|---|---|---|
| `ansible-core` | The binary resolves **on the PATH of the process that runs the toolkit**, and reports a version | Installed-somewhere is not the same as resolvable. Two failures need different fixes: not installed vs installed-and-cannot-execute |
| `galaxy collections` | Installed versions equal the `requirements.yml` pins | A drifted collection parses fine and behaves differently |
| `ansible.cfg` | The config file Ansible actually reads is `infra/ansible/ansible.cfg` | Ansible reads exactly one config, the first it finds. Run from elsewhere and you get the default — where a host-pattern mismatch is a warning and exit 0 (lesson-356, #1228) |
| `static inventory` | `infra/ansible/inventories/homelab.yml` parses and carries hosts | Needs neither `ansible-playbook` nor `ansible-galaxy`, so it still answers on a machine where nothing else runs |

The first check is deferred into the others: if `ansible-playbook` does not run,
the collection check reports `unverified` rather than inventing a verdict.

## Recipe: a WSL controller on the seat

Measured 2026-11-08 on Ubuntu 24.04 / Python 3.12.3. Note what the distro does
**not** give you: no `make`, no `poetry`, no global `ansible-core`, and `pip` is
blocked by PEP 668.

**Verified on the seat (Windows)** — the CLI renders and fails correctly, exit 1:

```
[ERROR] ansible-core: `ansible-playbook` is installed but does not run:
OSError: [WinError 87] The parameter is incorrect
[INFO]     FIX: run this from WSL or a Linux host; ansible-core has no Windows controller
[ERROR] galaxy collections: cannot be read without a working `ansible-galaxy`;
infra/ansible/requirements.yml is unverified
[ERROR] ansible.cfg: cannot be read without a working `ansible-playbook`
[SUCCESS] static inventory: 7 hosts under `all`
[ERROR] 3 of 4 checks failed
```

**Verified in WSL** — the same four checks, 4/4 OK, exit 0, driven through
`diagnose()` with `PATH` pointing at the checkout's venv.

**The bootstrap is a script, not a recipe** — `scripts/bootstrap-controller.sh`.
It exists because the tools below `make` cannot be installed *by* `make`: the
entry point has to be something that already runs. It installs GNU make and the
pinned Poetry, then hands off to `make setup-ansible` for the venv, the
collection pins and the doctor — those stay in one place rather than being
copied here.

```bash
bash scripts/bootstrap-controller.sh --check   # report only; installs nothing
bash scripts/bootstrap-controller.sh           # install what is missing, then setup-ansible
```

`--check` is the safe first move on any unfamiliar host: it names what is
missing and exits non-zero without touching the machine. Idempotent — anything
already correct is left alone. It refuses to run in a Windows shell (Git Bash
included), naming the `WinError 87` it would otherwise surface three steps
later.

It does not manage interpreters: if `python3` is below the floor that
`pyproject.toml` declares, it says so and stops rather than installing one.

**`--check` ends by running the doctor, and that is the point.** Whether a host
can be a controller is not answered by `command -v`: a machine with `python3`,
`make` and `poetry` and no `ansible-core` in the venv used to reach
`0 check(s) failed` and be told it could be a controller. So the last step asks
the only authority — `make check-ansible`, which reads the venv's
`ansible-core`, `ansible.cfg` and the collection pins against
`requirements.yml`. The doctor reports and installs nothing, so the mode stays a
dry run. When it cannot be asked (`make` unusable, or no venv yet) the line says
`ansible-core is unverified` instead of assuming either way.

**Verified in WSL 2026-11-09** — `--check` on a host that has none of it. It
reports, installs nothing, and exits 1:

```
python3 (>= 3.12, per pyproject.toml)
  [ok]   python3 3.12.3 (/usr/bin/python3)

GNU make
  [FAIL] make is not installed
         would install: make

Poetry 2.5.1
  [FAIL] poetry is not installed
         would install: poetry 2.5.1

ansible-core and the collections
         --check: installs nothing; 'make setup-ansible' is what creates the venv
         ansible-core is unverified: the doctor runs through make, unusable above

[ERROR] 2 check(s) failed
```

And on the host that is the reason for the doctor call — every prerequisite
present, `ansible-core` missing. Driven in WSL with stub `python3`/`make`/
`poetry` on `PATH` (`$STUB` is the stub directory; the bare `3.12.3` is the
stub's own stdout, the version gate prints nothing), the doctor's refusal
reaches the exit status and the verdict is withheld:

```
python3 (>= 3.12, per pyproject.toml)
3.12.3
  [ok]   python3 3.12.3 ($STUB/python3)

GNU make
  [ok]   GNU Make 4.3

Poetry 2.5.1
  [ok]   poetry 2.5.1 ($STUB/poetry)

ansible-core and the collections
         --check: installs nothing; 'make setup-ansible' is what creates the venv
         running 'make check-ansible' (read-only: it reports, it does not install)
  [FAIL] ansible-core is not importable from the venv
  [FAIL] the doctor refused this machine; the output above names the repair
         the doctor is the only authority on this question, so --check does not restate it

[ERROR] 1 check(s) failed
```

The same stubs with `make check-ansible` exiting 0 give `[ok] the doctor
passed: ansible-core, ansible.cfg and the collection pins agree` and exit 0 —
so the mode is a real gate in both directions, not a step that always reports.

**Not yet measured**: the install path itself (`apt-get`, the Poetry installer,
then `make setup-ansible`), because it writes to the host and that window has
not been opened. `--check` is the half that can be measured without one.

Two caveats about the venv, both measured on the seat's Windows side and likely
to repeat:

- **Poetry may create the venv outside the checkout** (in the `pypoetry` cache),
  so `.venv/bin` is not where you expect. `shutil.which("ansible-playbook")` —
  which is what the doctor checks — then returns `None` and the first check fails
  with a correct message about a binary you can see is installed. `poetry run`
  prepends the right `bin` itself; a bare `python` does not.
- **`pip install` is not a fallback** on this distro; it refuses without
  `--break-system-packages`, and taking that flag is how a controller ends up
  disagreeing with the lockfile.

## Trap: BusyBox make parses this Makefile as garbage

If `make` answers

```
make: (makefile:178): expected separator
```

and **no target runs at all** — not even `make help` — you have BusyBox `make`,
not GNU make. This repo's `Makefile` uses `$(if ...)` inside a `define`
(`require_dev_env`), which BusyBox cannot parse, so the whole file is rejected
before any target is considered.

The `:178` is the line where that `define` sat on the day this was measured, and
it moves as the file grows: match `expected separator`, never the number.

There is deliberately **no guard for this inside the Makefile**: a guard would
have to run, and nothing in the file runs. The signature above is the detection.
Install GNU make, or use the `poetry run toolkit …` form directly.

Confirmed on the seat: `scoop` ships BusyBox `v1.38.0-FRP-5857` as `make`.

## What `make setup` guarantees, and what it does not

`make setup` runs `setup-python setup-poetry setup-dependencies setup-sops
setup-ansible setup-certs`, so a complete `make setup` on a GNU-make host leaves
a working controller behind.

It does **not** guarantee that on every host:

- `setup-python` upgrades `pip` and `setup-poetry` installs Poetry via `pip`.
  On a PEP 668 distro (Ubuntu 24.04 and later) both fail; install Poetry with the
  official installer instead, then run `make setup-ansible` on its own.
- `setup-certs` runs the dev Compose stack and is pinned to `ENV=dev`; it is not
  part of becoming a controller.
- On Windows the controller half cannot succeed at all — the failure is the
  platform, and the fix line says so.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `` `ansible-playbook` is not installed `` | binary absent from the toolkit's PATH | `make setup-ansible` |
| `` `ansible-playbook` is installed but does not run: … WinError 87 `` | Windows controller | run from WSL or a Linux host |
| `galaxy collections: not what … pins: …` | drifted from the pins | `poetry run ansible-galaxy collection install -r infra/ansible/requirements.yml` |
| `ansible.cfg: … is not in effect (Ansible reads nothing)` | wrong cwd, or no config found | run from the repo; the message names the file it found |
| `static inventory: … declares no host` | inventory regenerated for an env with no hosts | check `infra/ansible/inventories/homelab.yml` |
| `make: (makefile:<line>): expected separator` | BusyBox make | install GNU make |
| `bootstrap-controller.sh: refusing to run under …` | Git Bash / MSYS shell on Windows | run it from WSL or a Linux host |
| `set: pipefail: invalid option` or `$'\r': command not found` | CRLF working-tree copy of a `.sh` | re-checkout the file; `.gitattributes` normalises on commit, not on disk |

## Related

- `docs/runbooks/add-a-node.md`, `docs/runbooks/k3s-setup.md` — the work a
  controller is for.
- `docs/runbooks/onboard-tenant-node.md` — the enrollment path that needs it.
- `infra/ansible/requirements.yml` — the collection pins.
- TOOL-131 (#3202) — why this runbook and the doctor exist.
