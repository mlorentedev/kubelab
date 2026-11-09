---
id: lesson-726-a-winerror-87-at-ansible-import-is-not-a-path-bug
type: lesson
status: active
created: "2026-11-09"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, windows, wsl, controller]
---

# A `WinError 87` at `ansible` import is not a path bug — `ansible-core` has no Windows controller

**Context**: a Windows seat (`msi`) was being used as the Ansible controller,
running `toolkit infra ansible doctor` and `make check-ansible` to decide
whether the seat could drive the VPS canary. `ansible-playbook` was installed
in the project venv and on `PATH`.

**Problem**: every `ansible-*` entry point died the same way, before parsing a
single argument:

```
$ poetry run ansible-playbook --version
  File "...\ansible\cli\__init__.py", line 54, in <module>
    check_blocking_io()
  File "...\ansible\cli\__init__.py", line 46, in check_blocking_io
    if not os.get_blocking(fd):
OSError: [WinError 87] The parameter is incorrect
```

`The parameter is incorrect` reads like a malformed path, a bad drive letter, a
UNC path, or a broken inventory file, and that is how it gets triaged: reinstall
`ansible-core`, re-check `PATH`, quote the paths, run from a shorter directory.
None of it changes anything, because the failure is at **import** and names a
POSIX-only API. `os.get_blocking()` exists on Windows but not with the semantics
`check_blocking_io()` needs — it cannot be made to work, so `ansible-core` calls
it unconditionally and refuses the platform rather than degrade silently.

The trap is the error's shape, not its content: it is raised from
`ansible/cli/__init__.py`, so it looks like one code path of one subcommand.
It is the shared import of every one of them — `ansible-playbook`,
`ansible-galaxy`, `ansible-inventory`, `ansible-vault` — which is why no
combination of subcommand and flag gets further.

**Solution**: treat `sys.platform == "win32"` as the diagnosis, not the error
string. `toolkit infra ansible doctor` does exactly that and prints a different
fix than it would for a genuinely broken install:

```
FIX: run this from WSL or a Linux host; ansible-core has no Windows controller
```

`make check-ansible` and `make setup-ansible` both refuse the platform up front
and name the `WinError 87` they would otherwise surface three steps later, and
`--require-fresh`'s Galaxy guard reports it as a controller that cannot list its
collections rather than as drifted pins. The controller is then a WSL distro on
the same machine, which is a Linux host as far as `ansible-core` is concerned.
Procedure: [`docs/runbooks/ansible-controller.md`](../../runbooks/ansible-controller.md).

**Rule**: a platform refusal must be detected by platform, never by parsing the
exception it produces. When an error's message names a mechanism ("the parameter
is incorrect") rather than a decision, check whether the library has already
decided the platform cannot work — and if it has, no configuration on that
platform is a fix. Corollary for this repo: a Windows seat is a valid place to
*develop* against the toolkit, and never a place to *run* Ansible, so any gate
that shells out to `ansible-*` has to say which side of that line it is on.

**Tags**: `#ansible` `#windows` `#wsl` `#controller` `#pr-3202`
