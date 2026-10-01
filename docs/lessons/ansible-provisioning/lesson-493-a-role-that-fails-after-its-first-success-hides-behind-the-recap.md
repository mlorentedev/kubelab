---
id: lesson-493-a-role-that-fails-after-its-first-success-hides-behind-the-recap
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, idempotence, jinja, dev-node]
---

# Three convergence bugs in one role each looked like a different symptom, and the recap showed none of them

**Context**: #1300 said the `dev_node` role reported `changed=3` on every pass. Its last comment had narrowed that to one task: npm prints `changed N packages` for a no-op, so a `changed_when` matching `'changed' in stdout` was always true.

**Problem**: Fixing that task exposed two more bugs, each hidden behind the one before it.

- **`ansible_managed` is undefined outside `template`.** ansible-core 2.19 stopped exposing it to other modules. A `copy:` whose inline content began with `# {{ ansible_managed }}` failed, so every task after the Gitea ssh drop-in had stopped running. The forge key had been generated but never registered, and no pass had ever got that far.
- **Jinja reads `'\2'` as `chr(2)`.** The role decided whether its key was already on the forge by listing every key and running `regex_replace('^(\S+)\s+(\S+).*$', '\2')`. Jinja unescapes string literals like Python, so the replacement was the control character and no key ever matched. The first pass POSTed the key and got a 201, which `uri` reports as `ok`. Every pass after it POSTed again into a 422.

**Solution**:
- Install the npm package with `community.general.npm` and `state: present`. It is not pinned, because Claude Code updates itself in place.
- Write a literal header in the inline content.
- Ask the forge `GET /user/keys?fingerprint=<sha256>` and POST only when that list is empty, with `changed_when: status == 201`.

Two consecutive provisions then reported `ok=57 changed=0 failed=0`, and `ssh -T` from ace2 authenticated as the machine identity for the first time.

**Rule**:
- **Run a fix to the end of the role, and keep running it.** A converging task can unmask a failing one behind it, and a recap that ends early counts nothing after the failure.
- **Never write a backreference as `'\N'` in a Jinja string.** It becomes a control character, and the regex silently replaces with garbage.
- **When an API can answer "does this exist" by a derived key such as a fingerprint, ask it.** Parsing a full listing is the fragile path.
- **Give every POST a truthful `changed_when`.** `uri` calls a 201 `ok`.

**Tags**: `#idempotence` `#jinja` `#issue-1300`
