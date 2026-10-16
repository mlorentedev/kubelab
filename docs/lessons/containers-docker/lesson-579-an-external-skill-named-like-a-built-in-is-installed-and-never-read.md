---
id: lesson-579-an-external-skill-named-like-a-built-in-is-installed-and-never-read
type: lesson
status: active
created: "2026-10-16"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, hermes, skills, ai-012]
---

# A managed skill named like a Hermes built-in is installed, listed, and never read

**Context**: AI-012 PR 5 gives hermes-kubelab the vault's cross-agent skills through `skills.external_dirs`, a read-only mount of root-owned copies. The first manifest declared `systematic-debugging` and `insights`.

**Problem**: the dry run reached the live gateway's `hermes skills list` and printed `systematic-debugging | software-development | builtin | builtin | enabled`. The image ships a built-in of that name, and external directories rank below the data directory's own skills (project, local, created, then external). So the vault's copy would have been copied, mounted, and shadowed: the provision green, the agent running a different procedure than the manifest said. `test-driven-development` has the same collision.

**Solution**: the manifest declares only names the image does not ship (`insights`), with the collisions named in the SSOT's comment. The provision reads the skills back from the running gateway and requires each declared name to be listed with the source `external`: a name that is only present, as a `builtin` row, fails. (The first version matched the name anywhere in the listing and would have passed on exactly the collision; PR-Agent caught it.) It also tries a write into the mount as the gateway's user, which must fail. Both tasks are skipped in a dry run, which cannot have a mount it did not create.

**Rule**: a name in two layers is a decision made by the precedence rules, not by the manifest. Before declaring an external skill, list the built-ins of the pinned image; and check a mechanism by the gateway's own view of it, since "copied and mounted" proves neither that it is read nor that it is read-only.

**Tags**: `#hermes` `#skills` `#ai-012`
