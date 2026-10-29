---
id: lesson-658-interpreter-discovery-follows-the-ssh-users-path
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, ansible, python, mise]
---

# Interpreter discovery takes the SSH user's PATH, so a dev-tool shim runs every module as root

**Context**: A dry run of `make provision NODE=ace2 ENV=prod CHECK=1` for #2798. The generated inventory set `ansible_python_interpreter: auto_silent`.

**Problem**: The second play hung in `Gathering Facts` for more than six minutes, with no output and no timeout. ace2's processes showed `sudo -H -u root .../mise/shims/python3.12 AnsiballZ_setup.py`, sitting in `poll()` on its own socket pair. Discovery takes the first name in its fallback list that the SSH user's shell finds on `PATH`, and `python3.12` comes before `/usr/bin/python3`. On ace2, the developer node, the operator's dev environment had put mise's shims first on 2026-10-28. As `manu` the shim works, which is why the pre-flight play (`become: false`) passed. Run as root with `HOME=/root`, it never returned. No other node had the shim, so nothing else showed it.

**Solution**: The inventory now declares `/usr/bin/python3` for every host (#2802), and `tests/test_generator_ansible.py` fails if it is changed or a host overrides it. The same dry run with `EXTRA='ansible_python_interpreter=/usr/bin/python3'` gathered facts at once and finished `failed=0`. The controller's implicit `localhost` is unaffected: Ansible sets its interpreter as a host variable, which outranks the `all` group, and it still reads Ansible's own Python.

**Rule**: Pin the managed node's system interpreter in the inventory. With discovery, whatever a developer tool puts first on the SSH user's `PATH` runs every module as root. A run that passes `become: false` and hangs as soon as it becomes root points here.

**Tags**: `#ansible` `#interpreter` `#pr-2802`
