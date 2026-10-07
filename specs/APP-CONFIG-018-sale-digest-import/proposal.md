---
id: "APP-CONFIG-018-sale-digest-import"
type: spec
status: verifying # draft | implementing | verifying | archived
created: "2026-10-07"
issue: "mlorentedev/kubelab#2088"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "time-boxed: the sale ends 2026-11-09 and the repository already holds 25 active specs, none of them this change's to abandon (25 active, limit 10, 2026-10-07)"
---

# APP-CONFIG-018-sale-digest-import

> **Naming**: file lives at `<repo>/specs/APP-CONFIG-018-sale-digest-import/proposal.md`. `APP-CONFIG-018-sale-digest-import` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

leaving-denver's daily sale-metrics digest (mlorentedev/leaving-denver#225) is not in prod n8n: it exists only as a JSON in that repository, with three values read from `$env` and two credentials to make by hand. n8n 2 blocks `$env` in nodes, and an env value read once at start goes stale silently (lesson-404), so the workflow cannot work as delivered. The sale ends 2026-11-09, so it has to be imported through `make import-n8n ENV=prod`, as code, within weeks. It is also the first workflow here that sends email, and other apps will reuse that capability.

## What

`make import-n8n ENV=prod` reconstructs the digest, its Cloudflare Header Auth credential and a shared SMTP credential from git and SOPS, with no UI step. Staging is untouched.

1. **The workflow** is `infra/n8n/workflows/sale-metrics-daily-digest.json` (fixed ids, one catalog entry, `envs={"prod"}`). Like its siblings it goes live at import (`publish:workflow`); the first email arrives at the next 08:00 Denver.
2. **The three values** (`SALE_DIGEST_TO`, `SALE_DIGEST_FROM`, `CF_WEB_ANALYTICS_SITE_TAG`) become `RESOLVE_*` placeholders filled at import. The sender is `infra.smtp.user` (a Gmail relay refuses any other From). The recipient and the site tag are SOPS values: the sale's own, and leaving-denver's runbook keeps them out of its public repository. Placeholder resolution no longer logs values, because a SOPS-resident value would otherwise reach the terminal.
3. **A shared credential registry** (`N8N_SHARED_CREDENTIALS`) declares credentials that belong to no workflow: `kubelab-smtp`, an n8n `smtp` credential rendered from `infra.smtp.{host,port,user,pass}`. It is upserted once per run, however many workflows reference it, and `secure` is derived from the port (465 is implicit TLS; 587 is STARTTLS, which n8n calls `secure: false`) because `infra.smtp.secure: true` means "require TLS" here, not "implicit TLS".
4. **A workflow is refused** if a node references a credential that nothing in the run imports, or two Header Auth nodes disagree on the id.
5. **The Cloudflare token** lives at `apps.services.automation.n8n.sale_digest.analytics_token`, beside the recipient and site tag in the same `sale_digest` block, all registered in `SECRET_CATALOG` for prod. An absent value fails the import closed before any `kubectl` call, naming the path.
6. **Sale lifecycle:** removal is one catalog entry, the JSON, the `sale_digest` SOPS block and its catalog entries, then deleting the workflow and the Header Auth credential in n8n. `kubelab-smtp` stays. A test pins that removing the sale entry leaves the shared credential imported.

## Out of scope

- Writing the Cloudflare token, recipient or site tag into SOPS: the owner mints and sets them.
- Running the import against prod, or `kubectl` of any kind.
- Staging coverage for the digest: it reads prod's dataset.
- Editing leaving-denver (its runbook, ADRs, decommission steps and the JSON copy).
- A second email workflow, or a generic notification path through Apprise.

## Risks / open questions

- The `sale_digest.*` values are absent from SOPS until the owner sets them, so the first prod import fails closed by design (named path, no `kubectl`).
- `infra.smtp.pass` is a Gmail app password and Gmail rewrites the From to the authenticated account, so a custom sender is not possible on this relay. The README says so.
- The Cloudflare Web Analytics GraphQL dataset is undocumented; the workflow already degrades to "unavailable" for that block.
- `make import-n8n ENV=prod` restarts n8n once, as for every run.

## Acceptance criteria

- [ ] AC1: a prod import creates the digest's Header Auth credential and `kubelab-smtp` before the workflow, once each, and a staging import does neither.
- [ ] AC2: an absent Cloudflare token, recipient, site tag or SMTP value fails that workflow's import before any `kubectl` call for it (the others still land), naming the SOPS path; no value appears in the output.
- [ ] AC3: a workflow referencing a credential the run does not import is refused; so is one whose Header Auth nodes disagree on the id.
- [ ] AC4: the `kubelab-smtp` payload matches n8n 2.12.3's `smtp` credential and derives `secure` from the port.
- [ ] AC5: with the sale entry removed from the catalog, a prod run still imports `kubelab-smtp` and never mentions the Cloudflare credential; two workflows sharing `kubelab-smtp` import it once.
- [ ] AC6: every new SOPS path is in `SECRET_CATALOG`, and every placeholder in a catalog workflow is mapped.
- [ ] AC7: the README documents the digest, how a workflow sends email, and the removal steps.

## References

- Bitácora: mlorentedev/kubelab#2088; leaving-denver#225
- ADR-036 (shared infra SMTP), ADR-035 (secret injection), TOOL-009 (import), `docs/runbooks/secrets-reference.md`
- leaving-denver: `docs/runbooks/kubelab-integration.md` section 3, `docs/runbooks/ops.md` "Sale metrics", ADR-011
