---
id: lesson-364-make-has-no-unknown-variable-error-so-an-unsupported-flag-is-a-real-run
type: lesson
status: active
created: "2026-08-21"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, makefile, ansible, safety]
---

# `make` has no unknown-variable error, so a flag one target ignores is a real run

**Context**: BACKUP-044 Part 5 wired the fleet notifier into `backup.yml`. To
check the wiring against real nodes without changing them, the obvious command
was the one the sibling target accepts:

```bash
make backup ENV=prod CHECK=1
```

`make provision NODE=vps ENV=prod TAGS=notify CHECK=1` had been used minutes
earlier and behaved exactly as a dry run should.

**Problem**: `make backup` did not thread `--check` through. It read:

```make
backup:
	@$(TOOLKIT) infra ansible run -p backup -e $(or $(ENV),prod)
```

`CHECK=1` was accepted as a variable assignment, went nowhere, and the target
ran. All four prod nodes — vps, rpi3, beelink, rpi4 — were changed by a command
believed to be read-only.

Nothing reported this. **`make` has no notion of an unknown variable**: any
`NAME=value` on the command line is a valid override of a variable that may or
may not exist. There is no typo error, no unused-variable warning, no non-zero
exit. The only signal was `changed=8` on a run expected to change nothing, and
that is a signal you have to already suspect to notice.

The second run gave it away — `ok` where the first had said `changed`. That is
the shape of an idempotent **real** deploy, not of two dry runs.

**Solution**: every Makefile target that runs Ansible against a node now threads
the flag, and a guard asserts it:

```make
backup:
	$(eval _CHECK := $(if $(CHECK),--check,))
	@$(TOOLKIT) infra ansible run -p backup -e $(or $(ENV),prod) $(_CHECK)
```

`tests/test_makefile_dry_run.py` scans the Makefile for
`$(TOOLKIT) infra ansible run -p <playbook>` and fails when one omits
`$(_CHECK)`, with a two-name allow-list for playbooks where a dry run is
meaningless. It checks itself first: the scan is a regex over recipe lines, so a
reformatted line would reduce the suite to zero assertions while still reporting
green, and a second test asserts the scan still finds what it guards — including
that no allow-list entry names a playbook the scan cannot see.

Consequences were benign here and that was luck, not design: the deployed change
was additive, the role it depended on had merged minutes before, and an
end-to-end delivery test (`make maintain-notify-test NODE=rpi3 ENV=prod` →
`Result=success, ExecMainStatus=0`) confirmed the fleet was left consistent.

**Rule**: **A safety flag that one target honours and its sibling ignores is not
an inconsistency to tidy up later — it is a live trap, and the trap is silence.**
Argument parsers reject unknown flags; `make` does not, and neither does a shell
variable. So the rule cannot be "remember which targets support `CHECK`". It has
to be enforced: either every mutating target accepts it, or a test says which do
not.

More generally: when a command that should have changed nothing reports
`changed=N`, stop and read the number before reading the output. The one place
this failure announces itself is the summary line everybody skims.

**Tags**: `#makefile` `#ansible` `#dry-run` `#safety` `#backup-044`
