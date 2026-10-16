---
id: lesson-583-a-mount-test-that-asserts-the-template-passes-a-path-the-consumer-never-sees
type: lesson
status: active
created: "2026-10-16"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, hermes, sandbox, ai-012]
---

# A mount test that asserts the template passes a path the consumer never sees

**Context**: AI-012 AC10 mounts a sparse checkout of the repository's `docs/` into the agent's sandbox. The checkout's work tree holds `docs/` one level down, because the checkout keeps the repository's own paths.

**Problem**: the template mounted the work tree, and the test asserted exactly what the template said, so both agreed on a path the sandbox never wanted. The provision ended `changed=11`, then `0`. Only listing the directory from a container started the way the agent's daemon starts it showed `/docs/docs/adr`.

**Solution**: the sandbox mounts the `docs` directory itself, as the bridge already did, and the test pins the path with the `docs` segment. The live read (`ls`, and a write that must be refused) goes into `verification.md`.

**Rule**: a test of a mount that compares the rendered string with the template's own variables checks the template against itself. Read the directory from inside the consumer once, and let the test pin that result.

**Tags**: `#hermes` `#sandbox` `#ai-012`
