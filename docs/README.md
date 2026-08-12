# Documentation

Project-bound knowledge (docs-as-code). The *build/operate* layer lives here, versioned with the code and readable by any agent in-context. The *decide/position* layer (roadmap, prestudy, strategy) and session memory live in the maintainer's cross-project knowledge store, not committed here.

## I want to…

| …do this | Start here |
|---|---|
| Understand what's versioned and how a release ships | [`architecture/versioning-strategy.md`](architecture/versioning-strategy.md) |
| Understand the CI/CD pipeline (workflows, runner routing) | [`runbooks/cicd.md`](runbooks/cicd.md) |
| Get a build from a merge into staging or prod | [`runbooks/gitops-delivery-promotion.md`](runbooks/gitops-delivery-promotion.md) — canonical deploy/promotion doc |
| Add a brand-new service to the platform | [`runbooks/new-service.md`](runbooks/new-service.md), [`runbooks/deploy-new-k3s-service.md`](runbooks/deploy-new-k3s-service.md) |
| Manage SOPS secrets | [`runbooks/sops-and-secrets.md`](runbooks/sops-and-secrets.md) (mechanics), [`runbooks/secrets-reference.md`](runbooks/secrets-reference.md) (catalog) |
| Restore a backup / PVC | [`runbooks/pvc-backup-restore.md`](runbooks/pvc-backup-restore.md) |
| Bootstrap or rotate the AWS ArgoCD hub | [`runbooks/aws1-destroy-replace.md`](runbooks/aws1-destroy-replace.md), [`runbooks/aws1-ebs-resize.md`](runbooks/aws1-ebs-resize.md) |
| Set up K3s on a node | [`runbooks/k3s-setup.md`](runbooks/k3s-setup.md), [`runbooks/k3s-upgrade.md`](runbooks/k3s-upgrade.md) |
| Diagnose a symptom (something's broken) | [`troubleshooting/quick-diagnostics.md`](troubleshooting/quick-diagnostics.md) — router into the rest of `troubleshooting/` |
| Read a past architecture decision | [`adr/`](adr/) — filename is `adr-NNN-slug.md`, no generated index yet ([D58](audits/docs-audit-2026-07-07.md)) |
| See what's actually deployed where | [`architecture/service-catalog.md`](architecture/service-catalog.md) — accuracy not re-verified since the 2026-07-07 audit ([D4](audits/docs-audit-2026-07-07.md)) |
| Check hardware/node topology | [`architecture/hardware/`](architecture/hardware/), [`architecture/infra/networking-topology.md`](architecture/infra/networking-topology.md) |
| Bootstrap a brand-new bare-metal node | [`runbooks/hardware-setup.md`](runbooks/hardware-setup.md) — **known stale** ([D9](audits/docs-audit-2026-07-07.md), pre-migration Proxmox world), not yet rewritten |
| Set up Headscale / the VPN mesh | [`runbooks/headscale-setup.md`](runbooks/headscale-setup.md) — **known stale** ([D15-D17](audits/docs-audit-2026-07-07.md), node roster + config paths), not yet rewritten |
| Debug staging/prod DNS | [`runbooks/dns-homelab.md`](runbooks/dns-homelab.md), [`runbooks/dns-and-domains.md`](runbooks/dns-and-domains.md) — **known stale** ([D18-D19](audits/docs-audit-2026-07-07.md)), not yet rewritten |
| Understand a past gotcha or post-mortem | [`lessons.md`](lessons.md) — chronological, 3k+ lines, no index yet ([D39](audits/docs-audit-2026-07-07.md)) |

## Directories

- [`adr/`](adr/) — Architecture Decision Records
- [`architecture/`](architecture/) — system/design docs
- [`runbooks/`](runbooks/) — operational procedures
- [`troubleshooting/`](troubleshooting/) — known issues & fixes
- [`audits/`](audits/) — point-in-time documentation/process audits
- [`lessons.md`](lessons.md) — accumulated gotchas & post-mortems

## Doc accuracy

This directory had two full audits on 2026-07-07 (`audits/docs-audit-2026-07-07.md`,
`audits/process-audit-2026-07-07.md`) that found the *recent* operational docs healthy but the
outer ring a newcomer reads first — architecture diagram, service catalog, versioning/CI/CD,
hardware/VPN setup — describing a platform two or three migrations old. Fixes are tracked
incrementally as **DOCS-002** ([#825](https://github.com/mlorentedev/kubelab/issues/825));
`versioning-strategy.md` and `cicd.md` are done, the rest of the table above is not. If a doc
you're reading contradicts what you observe in the code or cluster, trust the code — and file
or update the DOCS-002 ticket.
