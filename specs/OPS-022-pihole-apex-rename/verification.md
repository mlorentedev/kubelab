---
tags: [spec, verification, templates]
created: "2026-08-11"
---

# Verification - OPS-022-pihole-apex-rename

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test — split-DNS resolution (planned, not run yet): from a tailnet client using MagicDNS, `dig +short pihole.kubelab.live` should return `networking.nodes.ace1.tailscale_ip` — the same answer as AC2's authoritative-NS check, arrived at via the forward path (apex zone is outside the narrowed split-DNS, so rpi4/CoreDNS forwards to public DNS and picks up the Cloudflare record). Not a blocking acceptance criterion — Pi-hole's reachability is gated by network routing (tailnet-only IP), not by DNS, so this only verifies the resolution *path* works for VPN/LAN clients. If it fails while AC2 passes, the defect is in the rpi4/Headscale resolution chain, not in this change — record it and file a ticket against that chain rather than reopening this spec.
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

-
-

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons.md`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/<feature-id>/` -> `specs/archive/<feature-id>/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
