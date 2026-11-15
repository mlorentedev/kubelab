---
id: lesson-757-two-writers-of-one-mise-tool-fail-the-owner-that-checks
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, mise, dev-node, dotfiles, ownership]
---

# Two writers of one mise tool fail whichever owner checks its own pin

**Context**: `dotf update` on ace2, the developer node, to dotfiles 0.81.0. The converge stopped at its `tools` step with `after mise install, not running at their pin: node, python`.

**Problem**: The `dev_node` role rendered `~/.config/mise/config.toml` with node 24.19.0 and python 3.12.13. The dotfiles' converge wrote `~/.config/mise/conf.d/dotfiles.toml` from its `versions.conf` (node 24.22.1, python 3.13.16). mise gives `config.toml` precedence over `conf.d/`, so the shims kept resolving the role's versions. The dotfiles installed their pins, then their own post-install check correctly failed. Every step after `tools` (`lanes`, `git-hooks`, `configs-deploy`) never ran on ace2. Three tasks of the role also built paths from `dev_node_toolchains.node` (the npm install, the wrapper, the broken-npm repair), so deleting the pin alone would have broken them.

**Solution**: One owner per tool. The role pins only go, which the dotfiles do not put in mise. What needs node while the play runs (the npm install and the broken-npm repair) runs `mise where node` after the dotfiles bootstrap and uses that path. The bootstrap goes first because its `dotf tools sync` is what installs node on a fresh node. The `/usr/local/bin` wrappers resolve node on every call instead: the dotfiles' converge prunes node installs no config pins (`mise prune --yes --tools`), so a path saved at provision time dies the day they bump `NODE_VERSION`. Without the bootstrap, `--check` on a fresh host now stops at the assert that names it. The next provision re-renders `config.toml` without the two pins: on a copy of the old file, the first pass removed both lines and the second reported `changed=false`. The node and python installs the old pins left in `~/.local/share/mise/installs/` are orphans: the first `dotf converge` prunes them.

**Rule**: When a role and another deploy both write mise configs, list which tools each owns and keep the lists disjoint; a tool in both is shadowed by whichever file mise ranks higher, and the failure shows up in the other owner's check, not the role's. A consumer that needs the version of a tool it does not own asks the tool manager which one is active, and never copies the pin. `tests/test_dev_node_mise_owner.py` fails if the rendered config pins node or python, if any role file reads one from the defaults, or if a wrapper does not follow a node bump (it runs the rendered wrapper with a bare environment).

**Tags**: `#ansible` `#mise` `#ownership` `#issue-3559`
