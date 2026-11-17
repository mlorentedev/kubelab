---
id: lesson-764-retire-a-second-installers-leftover-before-the-owner-runs-and-by-path
type: lesson
status: active
created: "2026-11-16"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, poetry, pipx, dev-node, dotfiles, ownership, idempotence]
---

# Retire a second installer's leftover before the owner runs, and by path, not with the old tool's uninstall

**Context**: `make provision NODE=ace2` reported `changed=5` on three consecutive passes (#3577). One of the five was `pipx install --force poetry==2.2.1`. The dotfiles' bootstrap, which runs earlier in the same play, installs poetry 2.5.1 as a uv tool into the same `~/.local/bin/poetry`. The role's probe found 2.5.1, not its pin, and reinstalled 2.2.1 over the link; the next pass's bootstrap put 2.5.1 back. When the drill tag ran alone, with no bootstrap first, the probe answered 2.2.1 and the install was skipped, which is why the loop looked like a flaky probe and not like two owners.

**Problem**: Dropping the role's install (the same one-owner fix as #3566) leaves two things behind: pipx's venv, and, on a node whose last pass was the role's, a `~/.local/bin/poetry` link into that venv. Retiring them is where it goes wrong twice. `pipx uninstall poetry` unlinks whatever it finds at `~/.local/bin/poetry`, which after a bootstrap is the dotfiles' link. And a retirement placed after the bootstrap leaves a node with no poetry until the next converge, because the bootstrap has already run.

**Solution**: The role installs no poetry and asserts, with the cause, that the dotfiles' one runs (`dotf converge`). The leftover is retired by path with `file: state: absent`, before the bootstrap: the link only when it is a symlink pointing into `.local/share/pipx/venvs/poetry/`, the venv only when it exists, both only while the bootstrap that restores the link is on. Both conditions make the second pass `changed=0`. `tests/test_dev_node_poetry_owner.py` runs the real tasks against a temporary home: a pipx-linked home loses link and venv once and then changes nothing; a uv-linked home keeps its link and the uv tool directory is never touched.

**Rule**: A retirement must name only what the old installer created, and its condition must test that origin (where the link points), not that the path exists. Order it before the owner's install, so the owner's own output is what remains and the node is never without the tool. A probe-then-reinstall task that compares against a pin is a second owner by construction; a test that reads the YAML cannot show that, so run the tasks against a stand-in home and assert the second pass is `changed=0`.

**Tags**: `#ansible` `#poetry` `#pipx` `#ownership` `#issue-3577`
