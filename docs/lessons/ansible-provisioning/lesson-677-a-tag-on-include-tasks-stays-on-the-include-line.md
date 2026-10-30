---
id: lesson-677-a-tag-on-include-tasks-stays-on-the-include-line
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, ansible, tags]
---

# A tag on `include_tasks` stays on the include line; only `import_tasks` gives it to the tasks inside

**Context**: #1100 adds an assert that a play which reads `secrets` built them, in `_includes/require-secrets.yml`, run with `tags: [always]` so that `--tags <role>` cannot skip it. The repo's other includes are all reached with `include_tasks`.

**Problem**: `include_tasks` is dynamic. Its `tags:` decide whether the include line itself runs, and the tasks it loads keep only their own tags. Under `--tags role`, an `include_tasks` tagged `always` loads the file and every untagged task in it is then skipped. The run ends with exit 0 and no assert in the output, which is the silent pass the assert exists to stop. The existing `include_tasks` uses work only because they sit in a pre-flight play that is tagged `always` as a whole.

**Solution**: `import_tasks: _includes/require-secrets.yml` with `tags: [always]`. A static import copies its tags onto each imported task, and `ansible-playbook --list-tasks --tags node_notify` on `provision-rpi3.yml` lists `Require the play's secrets  TAGS: [always]`. `tests/test_require_secrets.py` runs both forms under `--tags role`. The import fails a play with no `secrets`, and the include passes it.

**Rule**: when a shared file must run under any `--tags`, import it (`import_tasks`, `import_role`) with the tag, or put the tag on the tasks inside it. A tag on `include_tasks` or `include_role` selects the include line only, unless `apply: {tags: [...]}` is given.

**Tags**: `#ansible` `#tags` `#pr-NNNN`
