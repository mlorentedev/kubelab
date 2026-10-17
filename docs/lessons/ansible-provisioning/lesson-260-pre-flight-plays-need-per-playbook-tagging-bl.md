---
id: lesson-260-pre-flight-plays-need-per-playbook-tagging-bl
type: lesson
status: active
created: "2026-05-19"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# Pre-flight Plays need per-playbook tagging — blanket `tags: [always]` breaks playbooks designed for one-time installs

**Context:** PR #181 added `tags: [always]` at Play level to the Pre-flight Play 0 of every `provision-*.yml` so that `make provision NODE=X ENV=Y TAGS=Z` would actually run the SSH / sudo / VPS reachability checks (which were previously skipped under any `--tags` filter). The rule was applied uniformly to all 7 provision playbooks (ace1, ace2, bee, rpi3, jetson, vps, aws1).
**Problem:** `provision-vps.yml` Pre-flight Play 0 is special: it is designed for **one-time first K3s install on VPS** (Pattern C migration). It asserts "K3s not yet installed" (fails if `/usr/local/bin/k3s` exists) and "Docker Compose Traefik is running" (pre-cutover assumption). Both invariants stop holding once the K3s cutover is complete. After PR #181 merged, every `make provision NODE=vps ENV=prod TAGS=monitoring` (the path PR #182 needed for VPS Glances migration) crashed during the Pre-flight on "Verify Docker Compose Traefik is running" — exactly the wrong place to fail. The regression was caught immediately during PR #182 live smoke, but required PR #183 to revert the change just for `provision-vps.yml`.
**Solution:** When applying a blanket pattern (e.g. tag everything `[always]`) across a fleet of playbooks, audit each playbook's *intent* first. Generic Pre-flight Plays (SSH + sudo + internet + key check) are safe to tag `[always]`. Playbooks with one-time-install assertions (`fail if <binary> exists`, `verify <service> running`) need either `[preflight]` only (manual invocation) or a `when:` guard wrapping the destructive asserts (`when: not <binary>.stat.exists`). Document the per-playbook intent in a comment block at the Play header so the next blanket-rule sweep does not silently regress it. PR #183 added exactly this comment to `provision-vps.yml`.
**Tags:** `#ansible` `#playbooks` `#tags` `#regression` `#lessons-from-fix`
