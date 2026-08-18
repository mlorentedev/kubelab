---
id: lesson-269-ssot-consolidation-category-inference-by-yaml
type: lesson
status: active
created: "2026-05-25"
owner: manu
tags: [kubelab, lesson, ssot, schema-design, ansible, ssot-014a]
---

# SSOT consolidation: category-inference by YAML position beats an explicit `category:` field

**Context:** SSOT-014a needed a per-category default for `ssh_user` (6 homelab nodes → "manu", 2 cloud nodes → "deployer"). Initial proposal had each node carry a `category: homelab|cloud` field so generators could group them. Alternative considered: infer category from the YAML structural position (under `networking.vps`/`networking.aws` → cloud; under `networking.nodes.*` → homelab).
**Problem:** Adding a `category:` field is schema overhead with zero discriminative value — the position in YAML already encodes the same information. Two declaration sites per node (position + category) invite future drift ("node moved to a different section but its category field wasn't updated"). The "category" was never really a property of the node — it was a property of the *bucket* the node lives in.
**Solution:** Use YAML position as the category signal. Generator (`generator_ansible.py:_resolve_ssh_user`) takes `category` as an arg passed by the calling loop — the loops over `networking.vps` / `networking.aws` / `networking.nodes.*` already know which bucket they're iterating, so they pass the right value at the call site. Per-node `ssh_user` override remains supported (unused today, free for future). Zero new schema fields, zero new tests for category drift. Lesson generalizes: before adding a discriminator field to a list of dicts, check if the list's *containing key* already encodes the discriminator — if it does, the field is duplication. Shipped in PR #218.
**Tags:** `#ssot` `#schema-design` `#ansible` `#ssot-014a`
