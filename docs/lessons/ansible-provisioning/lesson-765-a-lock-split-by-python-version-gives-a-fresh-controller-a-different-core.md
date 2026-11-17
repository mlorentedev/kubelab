---
id: lesson-765-a-lock-split-by-python-version-gives-a-fresh-controller-a-different-core
type: lesson
status: active
created: "2026-11-17"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, ansible-core, poetry, controller, pinning]
---

# A lock split by Python version gives a fresh controller a different ansible-core than the old one

**Context**: `make provision NODE=ace2 ENV=staging TAGS=dev_node` failed at `Vendor tmux-resurrect at a pinned version` with `'NoneType' object has no attribute 'startswith'` (#3623). The node was fine. The controller's `ansible-core` was 2.22.0, and an older venv on the same checkout ran the same task on 2.21.4.

**Problem**: `pyproject.toml` said `ansible-core = "^2.19"`, and `ansible-core` 2.22 requires Python 3.13, so `poetry.lock` held two entries: 2.21.6 for Python 3.12 and 2.22.0 for 3.13. "Locked" therefore did not mean one version: a venv created fresh on 3.13 got 2.22.0, a venv that predated it stayed on 2.21.x, and nothing reported the difference. On 2.22.0 `ansible.builtin.git` crashes when it updates an existing shallow clone checked out at a tag (`depth: 1`, `version: v4.0.0`): run 1 of a fresh clone changes, run 2 fails; 2.21.4 passes on that clone, and 2.22.0 passes without `depth`. Every provision of an existing dev node takes that path.

**Solution**: The range is capped (`>=2.19,<2.22`) and `poetry.lock` resolves one entry, 2.21.6, for every Python. `toolkit infra ansible doctor`, which `make provision` and `make setup-ansible` run first, reads the range from `pyproject.toml` and refuses a controller whose `ansible-playbook` is outside it, naming #3623 and `make setup-ansible` (which `poetry install` turns into a downgrade: measured 2.22.0 to 2.21.6). A range with no ceiling is itself refused. The Galaxy listing also ran with `ANSIBLE_VERBOSITY` stripped from its environment: at verbosity 1 `ansible-galaxy` prints a banner on stdout ahead of the JSON, which failed the check that a diagnostic run depends on. Lift the cap when a release passes the reproduction in #3623.

**Rule**: A controller's tool version is part of what a play was tested on, so pin its ceiling in the range and check the installed binary against the range, not only the lock: a lock with per-Python markers is several locks. A test that reads `poetry.lock` and asserts every `ansible-core` entry is inside the range keeps the two from drifting apart again. `tests/test_ansible_doctor.py` and `tests/test_galaxy_collections_pinned.py`.

**Tags**: `#ansible` `#ansible-core` `#poetry` `#issue-3623`
