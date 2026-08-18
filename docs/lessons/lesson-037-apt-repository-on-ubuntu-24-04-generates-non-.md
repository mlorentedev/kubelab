---
id: lesson-037-apt-repository-on-ubuntu-24-04-generates-non-
type: lesson
status: active
created: "2026-03-19"
owner: manu
tags: [kubelab, lesson]
---

# apt_repository on Ubuntu 24.04 generates non-obvious filenames

**Context**: Docker role cleaned `rm -f /etc/apt/sources.list.d/docker*` to remove old Docker sources.

**Problem**: `apt_repository` on Ubuntu 24.04 generates filenames based on the repo URL, not the package name. Docker's source file is named `download_docker_com_linux_ubuntu.list`, not `docker.list`. The glob `docker*` missed it.

**Solution**: Use Ansible `find` module with pattern `*docker*` (matches substring) instead of shell glob `docker*` (matches prefix only).

**Rule**: When cleaning apt sources, search by substring (`*docker*`), not prefix (`docker*`). Better yet, use `find` module for reliable matching.

---
