---
tags: [spec, verification]
created: "2026-05-13"
---

# Verification - AI-001-ollama-public

> Skeleton — fill at implementation time.

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof.

- [ ] `GET /api/tags` returns 200 with auth -> commit `<hash>` / test `<name>`
- [ ] Same endpoint returns 401 without auth -> commit `<hash>` / test `<name>`
- [ ] `POST /api/generate` completes inference end-to-end -> commit `<hash>` / smoke output
- [ ] Existing prod E2E suite zero regressions -> CI run `<link>`
- [ ] Cert provisioned for `ollama.kubelab.live` -> Traefik dashboard / `kubectl get ingressroute`
- [ ] LAN/Tailscale access unaffected -> smoke from ace1

## Test status

- E2E suite: `<command> -> <output>`
- Manual smoke: <what was exercised, what observed>
- No regressions: <yes / no>

## Decisions made during implementation

- Auth choice locked: <BasicAuth | Authelia | Custom header> — one-line rationale.
- Other non-obvious trade-offs: <list>

## Promotion candidates

- [ ] Lesson for `kubelab/90-lessons.md`? <yes / no — what>
- [ ] ADR-worthy decision for `kubelab/30-architecture/adr-XXX.md`? Likely yes if auth choice sets precedent for AI-004/005.
- [ ] New pattern candidate for `00_meta/patterns/`? Only if approach recurs in other repos.

## Archive checklist

- [ ] `proposal.md` frontmatter -> `status: archived`
- [ ] `mv specs/AI-001-ollama-public/ -> specs/archive/AI-001-ollama-public/`
- [ ] Backlog entry in `kubelab/11-tasks.md` ticked with PR link
- [ ] Promotions above executed (if any)
