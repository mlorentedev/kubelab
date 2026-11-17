---
id: lesson-763-ask-the-tool-manager-for-the-executable-not-the-install-and-a-layout
type: lesson
status: active
created: "2026-11-16"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, mise, dev-node, dotfiles, ownership]
---

# Ask mise for the executable, not for the install directory plus a layout

**Context**: `claude` had two owners on ace2: the dotfiles' converge installs it through mise (`claude = "latest"`, aqua backend) and the `dev_node` role installed `@anthropic-ai/claude-code` with npm. Option A of #3566 made the dotfiles the only owner, so the role's `/usr/local/bin/claude` wrapper had to point at the mise binary.

**Problem**: The wrapper was `exec "$(mise where node)/bin/<item>"`, which assumes every tool keeps its entry points under `bin/`. node does. The aqua `claude` is one binary at the install root: `mise which claude` answers `.../installs/claude/latest/claude`, and there is no `bin/`. Setting the wrapper's tool to `claude` would have rendered a clean file that exec'd a path that does not exist, and the fake `mise` of the old test, which only answered `where node`, could not have shown it. The two installs also sat in different directories, so nothing collided and nothing reported the drift between them.

**Solution**: Every mise-wrapped tool (node, npm, npx, claude) resolves with `mise which <item>`, asked from the dev user's home with its HOME, on every call. `which` returns the real file, not a shim (measured: `mise which npm` is `.../installs/node/<v>/bin/npm`), so npm's `BASH_SOURCE` resolution still works. The role's npm install task and its package list are gone. `tests/test_dev_node_mise_owner.py` lays claude out without `bin/`, answers only `mise which`, and runs the rendered wrappers across a version bump that prunes the old tree; `tests/test_dev_node_npm_converges.py` fails if the role installs anything with npm again.

**Rule**: A wrapper asks the tool manager where the executable is and never rebuilds the path from an install directory, because where an executable sits in an install is the backend's business. A tool needs one owner; a second install of it that "does not collide" only means the disagreement is not yet visible. A test double that answers one query shape hides every other layout, so make the fake answer the query the consumer asks and give it the awkward layout.

**Tags**: `#ansible` `#mise` `#ownership` `#issue-3566`
