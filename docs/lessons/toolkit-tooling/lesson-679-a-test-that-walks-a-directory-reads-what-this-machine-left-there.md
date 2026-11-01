---
id: lesson-679-a-test-that-walks-a-directory-reads-what-this-machine-left-there
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, testing, git]
---

# A test that walks a directory reads what this machine left there

**Context**: A full `make test` on a clean master checkout, run to get a baseline before other work.

**Problem**: Six tests in three files were red locally and green in CI: 4 errors in `tests/test_ansible_ssot_paths.py`, one failure in `test_apt_sources_deb822.py` and one in `test_coredns_role_inputs.py`. Seven tests read the Ansible tree with `ANSIBLE.rglob(...)`. A walk also reads `infra/ansible/generated/`, which is gitignored. In this checkout it still held playbooks a generator wrote in February 2026. The generator has since stopped writing them, and they no longer parse. A fresh CI clone has no such directory, so CI could not see the failure. Two of the tests had their own exclusion (`GENERATED not in p.parents`, `"generated" in path.parts`), and each covered only its own file.

**Solution**: `tests/repo_files.py` lists the files under a path with `git ls-files --cached --others --exclude-standard`. That covers every tracked file, plus every untracked file git would add, so a file written for a change is read before anyone stages it. All seven tests use it now, and the two exclusions are gone. `tests/test_repo_files.py` plants a malformed file under `generated/`, which also works on a CI clone where that directory does not exist. It also fails on any test that walks the tree again. With the stale files present, the seven files went from `2 failed, 4 errors` to `148 passed`.

**Rule**: A test that judges the source should list the source the way git does, not walk the disk. Whether a gitignored file exists depends on what ran on the machine, so a test that reads it gives a different verdict on each machine. A failure that only appears locally is the sign of this.

**Tags**: `#testing` `#git` `#pr-2858`
