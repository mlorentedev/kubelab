---
id: lesson-534-a-template-test-that-renders-without-trim-blocks-is-not-testing-what-ansible-ships
type: lesson
status: active
created: "2026-10-07"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, jinja, testing, shell]
---

# A template test that renders without `trim_blocks` is not testing what Ansible ships

**Context**: `node-backup-capture.sh.j2` gained a loop that builds the `find` prune
expression from every declared database and exclusion. The loop sat across shell
continuation lines, one `-o -path` per line. `tests/test_node_backup_role.py`
renders the template with a plain `jinja2.Environment` and runs the result.

**Problem**: Ansible's `template` module renders with `trim_blocks=True`, which drops
the newline after each `{% %}` tag; a bare `Environment` keeps it. The two render the
same loop to different scripts. In the test's rendering each tag left an empty line,
and an empty line after a `\` ends the shell command there, so `find` ran without its
action and the rest became separate commands. A loop written to look right under one
setting is broken under the other, and the tests only ever exercised the setting the
node never uses.

**Solution**: the prune expression is rendered on one line with inline tags, which
both settings render identically, and the tests that execute the capture script now
render it with `trim_blocks=True`, as the node gets it (`_render(..., _trim_blocks=True)`
in `_capture`). Verified on beelink: the deployed `/opt/node-backup-capture.sh` carries
the expression on one line, `changed=1` then `changed=0`, snapshot `d3f8edaa`.

**Rule**: a test that executes a rendered Ansible template renders it with Ansible's
settings (`trim_blocks=True`), or it is testing a script no node runs. Inside a shell
continuation, keep Jinja tags inline so whitespace control cannot split the command.

**Tags**: `#jinja` `#ansible` `#node-backup` `#testing`
