---
id: lesson-748-a-version-directory-says-a-toolchain-was-installed-not-that-it-runs
type: lesson
status: active
created: "2026-11-13"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, mise, npm, dev-node]
---

# A version directory says a toolchain was installed, not that it runs

**Context**: Collecting ANSIBLE-037's AC1 evidence with an untagged `make provision NODE=ace2 ENV=staging`, run twice.

**Problem**: Both runs failed at `Install global agent CLI tools via mise node npm` with `No such file or directory: .../mise/installs/node/24.19.0/bin/npm`. The version directory was there, so `mise ls --missing` reported nothing missing and the role skipped the install. Inside `bin/`, `npm`, `npx`, `corepack` and `yarn` sat under npm's temporary names (`.npm-4uhw1Y7s` and so on). npm renames a package's bin links aside while it replaces that package, and puts them back when it finishes. An `npm update --global` on 2026-10-31 was interrupted while extracting `npm@12.2.1`, so they were never put back. Run 2's `changed=0` meant nothing either, because both runs stopped at the same task.

**Solution**: The `dev_node` role now stats the npm the next task executes and runs `mise install --force node@<pinned>` when it is gone (#3477). The forced reinstall is scoped to the pinned node: a bare `--force` would rebuild every toolchain.

**Rule**: Check the entry point the next task runs, not the directory that holds it. A failed run's `changed=0` is not convergence evidence: read `failed=` first.

**Tags**: `#mise` `#npm` `#idempotence` `#issue-3477`
