---
id: lesson-357-a-guard-that-cannot-fail-reports-coverage-it-does-not-have
type: lesson
status: active
created: "2026-08-20"
owner: manu
category: process-method
tags: [kubelab, process-method, testing, ci-automation]
---

# A guard that cannot fail is worse than no guard

**Context**: One session, 2026-08-20, shipping BACKUP-044 Part 3 and hardening
the review machinery. Four separate guards were found green while checking
nothing. They were written by different means at different moments, which is
what makes the shape worth naming rather than each instance worth fixing.

**Problem**: Each one asserted something that was true by construction.

1. **A glob guard that re-implemented its subject** (#1180). To prove the
   Ansible gate's non-recursive glob never reaches `playbooks/_includes/`:

   ```python
   assert not any(p.parent.name == "_includes" for p in PLAYBOOKS.glob("*.yml"))
   ```

   A non-recursive glob's results all have the playbooks directory as their
   parent, so `p.parent.name` is never `_includes`. Switching the *gate* to
   `rglob` would have left this green — it checked its own glob, not the
   gate's.

2. **A coverage test that compared a file to its own derivation** (#1186). It
   stripped `kubelab-` from a playbook's `hosts:` patterns and compared the
   result to the declared source list. `kubelab-beelink` stripped to `beelink`,
   which was declared, so it passed — while `beelink` was the name the
   inventory actually used and the pattern matched **nothing**. Three of four
   nodes were silently skipped and the run reported success.

3. **A substring assertion against a shell block** (#1188). Guarding that an
   exit-0 condition stays narrow:

   ```python
   assert '[ "$CODE" = "0" ] || [ "$CODE" = "1" ]' in run
   assert 'exit 0' in run
   ```

   The second line is vacuous — the shape it replaced, `[ "$CODE" = "0" ] &&
   exit 0`, contains `exit 0` too. And the first is satisfiable by a *wider*
   guard: appending `|| [ "$CODE" = "2" ]` keeps the asserted substring
   present while making the error path unreachable.

4. **A verification whose failure was indistinguishable from its subject's.**
   Checking whether a fix had landed on a remote branch:

   ```
   gh api repos/.../contents/tests/x.py?ref=my-branch | ... | grep -c 'thing'
   → 0
   ```

   The zsh glob consumed `?ref=`, the command errored, and `grep -c` printed
   `0`. "Not present" and "I never looked" render identically.

The reviewer caught (1) and (3); a manual `--list-hosts` caught (2); re-reading
my own output caught (4).

**Solution**: In each case, anchor the assertion to the artifact that does the
work, and check the guard can go red.

- (1) now reads the gate's glob out of `toolkit/cli/infra.py` and asserts
  `rglob`/`**` are absent — verified by switching the gate to `rglob` and
  watching the test fail.
- (2) now asserts each `hosts:` pattern is a member of the inventory's
  namespace, derived the way `generator_ansible.py` derives it, plus a second
  test asserting the generator still derives it that way.
- (3) now extracts the condition with a regex and compares it **exactly**, so
  widening the accepted range fails.

**Rule**: A test whose expected value is computed from the actual value passes
by construction. When the subject is a name, a pattern or a shape that must
match something *outside* the file, assert against the external artifact — the
inventory, the generator, the workflow — never against a transformation of the
value under test.

And treat "can this fail?" as part of writing it, not part of reviewing it. The
cheapest proof is thirty seconds: break the thing deliberately, watch red,
restore. A guard only ever observed green is indistinguishable from one that
cannot go red — which is the same defect this repo's attestation gate exists to
catch in its reviewers, arriving inside the tests written to prevent it.

Corollary for verification commands: make failure distinguishable from
absence. A pipeline that reports `0` both when the thing is missing and when
the command never ran will confirm whatever you already believed.

**Tags**: `#testing` `#silent-failure` `#pr-1180` `#pr-1186` `#pr-1188`
