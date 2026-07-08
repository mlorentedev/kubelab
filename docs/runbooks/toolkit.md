---
id: "kubelab-runbook-toolkit"
type: runbook
status: superseded
superseded_by: toolkit/README.md
tags: [kubelab, project]
created: "2026-02-21"
updated: "2026-07-07"
owner: manu
---

# Toolkit Guide (retired)

> Retired by the 2026-07-07 docs audit (finding D20, `docs/audits/docs-audit-2026-07-07.md`):
> this guide taught an `ENVIRONMENT=` env-var pattern and commands (`tk terraform`,
> `services test`, `credentials generate <user> <pass>`) that the current CLI does not have.

The command reference is **[toolkit/README.md](../../toolkit/README.md)** (regeneration
from the CLI tree tracked as DOCS-002, #825) and `poetry run toolkit --help`.

The durable facts worth keeping:

- The toolkit runs **locally** on your dev machine via `poetry run toolkit` (alias `tk`)
  and manages all environments remotely — it is never installed on servers.
- Environment selection is always the `--env/-e` flag (e.g.
  `toolkit deployment deploy --env staging`), never an environment variable.
- Terraform lives under `toolkit infra terraform …`; secrets under `toolkit secrets …`.
