---
id: lesson-012-a-broken-language-toolchain-launcher-silently
type: lesson
status: active
created: "2026-06-20"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, poetry, python, pre-commit, dev-setup, windows]
---

# A broken language-toolchain launcher silently un-wires the dev setup

**Context**: Resuming work, `poetry` failed with `did not find executable at ...python-313...python.exe`, and pre-commit had clearly never run — `.git/hooks` held only `.sample` files and `core.hooksPath` was unset.

**Problem**: A Poetry console launcher (like venv shebangs) embeds the **absolute path** of the interpreter that created it. The Python 3.13 install had been removed (OneDrive relocation), orphaning the launcher. Because `poetry` itself was broken, `make setup` had never completed in this clone → `pre-commit install` never ran → no git hooks were wired, and nothing surfaced the gap at the time. The breakage stayed invisible until a hook was finally expected to fire.

**Solution**: Reinstall Poetry against a present, CI-parity interpreter — `py -3.12 -m pip install --user --force-reinstall poetry`, then copy the fresh `Python312\Scripts\poetry.exe` over the stale launcher — and `poetry run pre-commit install`. Reinstalled on 3.12.8 (CI parity), not the freshly-installed 3.14.

**Rule**: A toolchain whose launcher pins an absolute interpreter path breaks silently when that interpreter moves or is deleted, and a broken package manager can leave downstream setup (git hooks, venv) half-wired with no error. After any Python relocation/upgrade, re-run `make setup` and verify the chain end-to-end (`poetry --version`, hooks actually present under `core.hooksPath`) — a green shell prompt does not mean the dev environment is wired.

**Tags**: `#poetry` `#python` `#pre-commit` `#dev-setup` `#windows`
