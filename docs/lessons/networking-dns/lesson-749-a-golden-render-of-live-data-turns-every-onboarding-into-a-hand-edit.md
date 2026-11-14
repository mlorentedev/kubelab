---
id: lesson-749-a-golden-render-of-live-data-turns-every-onboarding-into-a-hand-edit
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, testing, self-service]
---

# A golden render of live data turns every onboarding into a hand edit

**Context**: EDGE-001 (#3495) moved the staging split-DNS zones from a hand list in `common.yaml` to `infra/config/products/edge.json`, derived from the product registry. The live edge (Corefile, Pi-hole forwarding, Headscale split, pod hairpin) had to stay byte-identical, so the change was pinned first with golden renders captured on master.

**Problem**: The first golden tests rendered the consumers from the committed manifest. They proved the zero diff, and then any new product would have failed them: onboarding a product adds a zone to `edge.json`, every golden differs, and a human has to regenerate four fixtures in the bot's PR. The headscale runbook test had the same shape, comparing the runbook's snippet with the whole effective list. A derivation that exists to remove hand steps had a test suite that added one per product.

The same derivation also showed a guard that lived only at the wrong layer. D8 refuses a staging hostname that is not `staging.<domain>` at render, but the derivation reads snapshots directly. A snapshot naming a bare apex such as `imagesensortool.com` would have become a split-DNS zone, sending every VPN client's prod lookups for that domain to the edge: the failure the 2026-03-03 narrowing of Headscale split DNS exists to prevent.

**Solution**: The goldens render from a frozen manifest written to `tmp_path` (`FROZEN_ZONES` in `tests/test_edge_dns_zero_diff.py`), so they test the templates, not today's registry. A separate test adds a zone and asserts it reaches all four consumers. The runbook test compares only the platform's declared zones, which must be the prefix of the rendered list. The derivation repeats the shape check (`staging_zone_for`), and `make mutate` turns three tests red without it.

**Rule**: A characterization test pins the transformation, not the data flowing through it: freeze its input. If a test must change whenever the system is used as designed, it is testing the data. A guard on a value that more than one reader consumes belongs in each reader that can act on it, or in the one place they all go through.

**Tags**: `#dns` `#testing` `#issue-3495`
