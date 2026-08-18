---
id: lesson-180-cloud-init-yaml-colons-in-strings-cause-parse
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# cloud-init YAML: colons in strings cause parse errors

**Context:** `echo "cloud-init complete: K3s ready"` in cloud-init runcmd was parsed as a YAML dict (`:` creates key-value). All runcmd commands failed silently.

**Solution:** Quote strings with colons, or use `>-` / `|` block scalars.

**Rule:** Always quote cloud-init runcmd entries that contain `:` characters. Test with `cloud-init schema --system` after boot.
**Tags:** `#cloud-init` `#yaml` `#gotcha`
