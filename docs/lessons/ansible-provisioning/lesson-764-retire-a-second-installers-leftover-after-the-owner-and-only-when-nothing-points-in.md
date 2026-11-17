---
id: lesson-764-retire-a-second-installers-leftover-after-the-owner-and-only-when-nothing-points-in
type: lesson
status: active
created: "2026-11-16"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, poetry, pipx, dev-node, dotfiles, ownership, idempotence]
---

# Retire a second installer's leftover after the owner has run, and only when nothing points into it

**Context**: `make provision NODE=ace2` reported `changed=5` on three consecutive passes (#3577). One of the five was `pipx install --force poetry==2.2.1`. The dotfiles' bootstrap, which runs earlier in the same play, installs poetry 2.5.1 as a uv tool into the same `~/.local/bin/poetry`. The role's probe found 2.5.1, not its pin, and reinstalled 2.2.1 over the link; the next pass's bootstrap put 2.5.1 back. When the drill tag ran alone, with no bootstrap first, the probe answered 2.2.1 and the install was skipped, which is why the loop looked like a flaky probe and not like two owners.

**Problem**: Dropping the role's install (the same one-owner fix as #3566) leaves pipx's venv behind, and on a node whose last pass was the role's, a `~/.local/bin/poetry` link into that venv. The tempting retirement removes both in the role. That makes the role a writer of `~/.local/bin/poetry` again, and it bets that the owner will recreate the link it just lost: a bootstrap that stops early (the #3559 converge stopped at `tools`) would leave the node with no poetry at all, and nobody had measured that the bootstrap recreates an absent link, only that it overwrites a foreign one.

**Solution**: The role installs no poetry and asserts, with the cause, that the dotfiles' one runs (`dotf converge`). The leftover venv is retired by path with `file: state: absent`, after the bootstrap, and only when the venv exists and `~/.local/bin/poetry` is not a symlink into it. The role never writes the link: after the bootstrap it is the dotfiles', and if the bootstrap did not replace it, the venv stays and the retirement waits for the next pass. Both conditions make the second pass `changed=0`. `tests/test_dev_node_poetry_owner.py` runs the real tasks against a temporary home: a uv-linked home loses the venv once and then changes nothing, a pipx-linked home keeps it, and the uv tool directory is never named.

**Rule**: A retirement removes only what the old installer created, and never what the owner has to write: it waits until nothing points into the leftover, so a failed or partial owner run can only delay the cleanup, never leave the node without the tool. Place it after the owner, not before. A probe-then-reinstall task that compares against a pin is a second owner by construction; a test that reads the YAML cannot show that, so run the tasks against a stand-in home and assert the second pass is `changed=0`.

**Tags**: `#ansible` `#poetry` `#pipx` `#ownership` `#issue-3577`
