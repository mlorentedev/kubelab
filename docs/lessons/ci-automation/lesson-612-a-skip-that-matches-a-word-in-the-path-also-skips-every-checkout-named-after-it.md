---
id: lesson-612-a-skip-that-matches-a-word-in-the-path-also-skips-every-checkout-named-after-it
type: lesson
status: active
created: "2026-10-21"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pytest, e2e]
---

# A skip that matches a word in the path also skips every checkout named after it

**Context**: #2572 added `tests/test_e2e_expectations_cover_registry.py`, an offline unit test, in a worktree named `test-e2e-expectations-cover-registry-2572`.

**Problem**: `make test-fast` reported `6341 skipped` in 29 seconds and nothing failed. `tests/e2e/conftest.py` skips the e2e suite when the target environment is unreachable, and it chose the items to skip with `"e2e" in str(item.fspath)`. Pytest calls `pytest_collection_modifyitems` with every collected item, not only the ones under the conftest's directory. So the substring matched the checkout's own path, and every test in the repository was skipped. In CI, which has no VPN, it would also have skipped any unit test whose file name contains `e2e`, including the new one. A skipped test is not a failure, so nothing reported it.

**Solution**: Match by directory instead: `item.path.resolve().is_relative_to(_E2E_DIR)`, where `_E2E_DIR` is the conftest's own directory. A test in the same file calls the hook with one item inside `tests/e2e` and one outside it whose path contains `e2e`, and asserts only the first is skipped. `make mutate` proved that test red against a `_E2E_DIR` of `/`.

**Rule**: A conftest hook that selects items sees the whole session, so select by structure (`is_relative_to`, a marker), never by a substring of a path. And when a suite reports an unusual number of skips, read the skip reasons before reading the result as green.

**Tags**: `#pytest` `#e2e` `#issue-2572`
