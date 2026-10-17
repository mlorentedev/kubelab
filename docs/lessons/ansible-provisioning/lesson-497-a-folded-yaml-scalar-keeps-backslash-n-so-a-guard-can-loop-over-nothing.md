---
id: lesson-497-a-folded-yaml-scalar-keeps-backslash-n-so-a-guard-can-loop-over-nothing
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, yaml, jinja, guards]
---

# A folded YAML scalar keeps `'\n'` as two characters, so a guard built on it can loop over nothing and report `skipping`

**Context**: The `agent_stack` role declares a subordinate id range for the agent's user on ace2 and asserts that no other user's range overlaps it. The assert loops over the lines of `/etc/subuid` and `/etc/subgid`, parsed from `slurp` with `join('\n') | split('\n') | select('match', ...)`. The expression sat in a folded scalar (`loop: >-`) to stay under the line limit.

**Problem**: The first provision on ace2 printed `skipping: [ace2]` for the assert, although `/etc/subuid` held `manu:100000:65536`. YAML processes escapes only in double-quoted scalars. In a folded or literal one, `'\n'` reaches Jinja as a backslash and an `n`. `join` and `split` then agree with each other on that two-character separator, and the files' real newlines never split. Each file became one element with embedded newlines, the anchored regex matched none of them, and the loop ran zero times. Ansible reports an empty loop as `skipping`, the same word it uses for a `when` that is false, so a broken guard read as a guard with nothing to check.

**Solution**: The expression moved into a double-quoted scalar, which can still be folded across lines and where YAML turns `\n` into a newline before Jinja sees it. A second assert makes the failure loud: the agent's own declared line must be among the parsed lines, twice (one per file), so a parse that returns nothing fails the play instead of passing it. `tests/test_agent_user_role.py::test_the_subordinate_id_parse_splits_on_a_real_newline` loads the task and asserts the value holds a real newline. It goes red when the expression is folded again (verified by mutation).

**Rule**: Write an escape a Jinja expression depends on inside a double-quoted YAML scalar, never a folded or literal one. Give every loop-based guard a positive control: one element the parse must find, asserted before the loop runs. `skipping` on a guard is a finding to read, not a pass.

**Tags**: `#yaml` `#jinja` `#ansible` `#guards`
