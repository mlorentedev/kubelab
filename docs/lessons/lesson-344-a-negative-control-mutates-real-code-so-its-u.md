---
id: lesson-344-a-negative-control-mutates-real-code-so-its-u
type: lesson
status: active
created: "2026-08-09"
owner: manu
tags: [kubelab, lesson, git, negative-control, verification, uncommitted-work]
---

# A negative control mutates real code, so its undo must be scoped to the experiment and not to the file

**Context:** Implementing TOOL-029 under the day's discipline of running every safeguard once against a state where it must fail. To prove a new test would catch a regression, I temporarily deleted one interpolation from the real apply in toolkit/cli/infra.py, confirmed the test went red, then restored the file with git checkout on that path.

**Problem:** That file also held the entire uncommitted implementation of the feature: two module constants, two helper functions, and the wiring into both apply sites. git checkout restores from the index, so it discarded all four edits, not only the one line the experiment had touched. The negative control passed, the restore looked clean, and nothing complained. The loss surfaced two steps later, when the full suite reported exactly 18 failures, the precise size of the new test file, with AttributeError saying the module had no attribute _spoke_service_account. Because those same tests had passed in isolation minutes earlier, the natural first hypothesis was fixture leakage or test interaction, which is a slow and entirely wrong road.

**Solution:** Re-applied the four edits from context and re-ran: 414 passed. The correct technique for a temporary mutation is a copy, writing the file aside and restoring from that copy, or staging the real work first so the index holds it and checkout becomes safe. Both scope the restore to the experiment rather than to the file. The rule: git checkout is not an undo, it is a reset to the last staged state, and its blast radius is the whole file no matter how small the experiment was. A useful tell for next time is that when a suite fails with a count exactly equal to a file just added, suspect the module under test vanished before suspecting the tests.

**Tags:** `#git` `#negative-control` `#verification` `#uncommitted-work`
