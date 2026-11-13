---
id: lesson-741-a-tool-broken-only-on-its-first-run-is-missing-a-lazily-imported-dependency
type: lesson
status: active
created: "2026-11-12"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, poetry, macos]
---

# A tool that fails only on its first run is missing a dependency it imports lazily

**Context**: `make worktree-init` failed the first time in every new worktree on the Mac and passed when run again, with nothing changed in between (#3399).

**Problem**: Poetry imports `xattr` only inside `build_venv`, to exclude a new venv from Time Machine. The `poetry` first on PATH was not the isolated copy dotfiles installs with `uv tool`. It was a second one that `make setup` had pip-installed into mise's Python 3.13 with its output thrown away, and that install had no `xattr` (`pip check`: `poetry 2.5.1 requires xattr, which is not installed`). The first run created `.venv` and then crashed on the import. The second found the venv already there, never reached the import, and passed. The symptom looked like a race; it was a broken install hidden behind a code path that runs once.

**Solution**: `setup-poetry` no longer pip-installs Poetry. It checks that one exists and otherwise names `uv tool install poetry`. `tests/test_setup_poetry_installs_nothing.py` fails if the pip install comes back. On the host, uninstall the stray copy so the isolated one wins: `python3 -m pip uninstall poetry` with mise's Python active.

**Rule**: When a command fails once and then passes, find what the first run creates; the code path that runs only on creation is where the fault is. Check with `which -a <tool>` and `python -m pip check`. Install a Python CLI in its own environment and never into an interpreter a version manager puts on PATH. A setup step that sends an install's output to `/dev/null` hides exactly this failure.

**Tags**: `#poetry` `#worktree` `#issue-3399`
