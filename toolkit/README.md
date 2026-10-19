---
id: "toolkit-readme"
type: readme
status: active
created: "2026-02-08"
owner: manu
---

# Toolkit

The Python CLI that turns KubeLab's declared state into generated files, secrets and deployments. Every Makefile target that touches infrastructure ends up here; run those targets rather than the CLI by hand (`make help` lists them).

```bash
poetry run toolkit --help          # the command tree, from the live CLI
make test-fast                     # the suite, without e2e, infra and integration marks
```

## Where the truth lives

- **Values** (non-secret): `infra/config/values/common.yaml`, overlaid by `dev.yaml`, `staging.yaml`, `prod.yaml` and `hub.yaml`. This is the single source of truth; generated files are never edited by hand.
- **Secrets**: SOPS-encrypted `infra/config/secrets/{common,dev,staging,prod}.enc.yaml`, reached only through `toolkit secrets` (`SECRET_CATALOG` in `toolkit/features/secrets_manager.py` is the registry).
- **Generated output**: `infra/config/platform.json` and the files `toolkit sync` renders. `make validate-sync ENV=<env>` fails when one has drifted from its source.

## Layout

| Path | Holds |
|---|---|
| `toolkit/main.py` | The Typer app: registers one group per module in `toolkit/cli/` |
| `toolkit/cli/` | Command groups: option parsing and wiring to `toolkit/features/` |
| `toolkit/features/` | The logic behind each command, importable and unit-tested without the CLI |
| `toolkit/core/` | Shared plumbing: logging, SOPS, templating, GraphQL and I/O helpers |
| `toolkit/config/` | `settings.py` (environment-aware settings) and `constants.py` |
| `toolkit/scripts/` | Standalone scripts that `sync` and the Makefile call |

## Commands

The table is generated from the command tree, never edited by hand. `toolkit tools cli-reference --write` refreshes it, and `tests/test_toolkit_readme.py` fails when it is stale.

<!-- cli-reference:start -->

| Command | What it does |
|---|---|
| `toolkit auth` | Identity operations (AUTH-004): access review, and break-glass while the IdP is down. |
| `toolkit auth break-glass` | Open the private way into SERVICE while Authelia is down (ADR-062 D4). |
| `toolkit auth review` | Access review: each app's live privilege against the declared groups (ADR-062 D2, D5). |
| `toolkit backup` | Offsite backup pipeline (Cloudflare R2 / restic). |
| `toolkit backup coverage` | Report the newest snapshot for every node in `backup.sources`, read from R2. |
| `toolkit backup drill-apps` | Restore the newest Authelia and n8n captures from R2 and check the SOPS keys open them. |
| `toolkit backup drill-gitea` | Restore the newest Gitea capture from R2 into a scratch server and check it brings the forge back. |
| `toolkit backup drill-headscale` | Restore the newest Headscale capture from R2 into a scratch container and check it is complete. |
| `toolkit backup drill-node` | Restore a node's newest capture from its own repository and check every declared source (BACKUP-076). |
| `toolkit backup drill-postgres` | Restore the newest Postgres dump from R2 into a scratch container and check it is complete. |
| `toolkit backup escrow-check` | Compare each restic password in SOPS with its Bitwarden escrow entry (BACKUP-057). |
| `toolkit backup generate-password` | Generate the restic repository password and store it in SOPS. |
| `toolkit backup health-check` | Run full R2 destination verification + fleet coverage check and notify Slack. |
| `toolkit backup isolation-probe` | Fail on any R2 request a stolen node credential should be refused (BACKUP-057). |
| `toolkit backup migrate` | Move one node's restic history into its own bucket (BACKUP-057 AC4). |
| `toolkit backup mint-node-tokens` | Mint each node's own R2 token and restic password into SOPS (BACKUP-057). |
| `toolkit backup restore-window` | Pause an env's Argo CD auto-sync and stop one app, so its data can be replaced (BACKUP-070). |
| `toolkit backup verify-destination` | Prove the R2 destination is usable: scope, reach, and a write/read/delete round-trip. |
| `toolkit backup verify-restic` | Prove restic can create, use and verify a repository in R2. |
| `toolkit board` | Bitácora board governance: keep the Stream field true to the registry. |
| `toolkit board deps` | Report open issues named by a dependency keyword in another open issue's body (GOV-005 AC3 guard). |
| `toolkit board ids` | Report (default) or check for open issues that share a ticket id. |
| `toolkit board parts` | Plan (default) or apply the parent links declared under `parts:` in the registry. |
| `toolkit board priority` | Report (default), apply, or check open issues with no Priority set. See harness/priority-scale.md. |
| `toolkit board set` | Set one issue's Status / Priority / Stream by NAME (TOOL-046, #1468). |
| `toolkit board streams` | Plan (default), apply, or check the Stream field against harness/board-streams.yaml. |
| `toolkit board sweep` | Plan (default) or apply the one-time In Progress sweep in harness/board-inprogress-sweep.yaml. |
| `toolkit config` | Manage configuration files and environment variables. |
| `toolkit config generate` | Generate configuration files from templates (Traefik, Ansible, Terraform). |
| `toolkit config get` | Print one NON-SECRET value from the SSOT, for scripts and Makefile targets. |
| `toolkit config validate` | Validate generated configuration files (sanity check). |
| `toolkit credentials` | Generate credentials and manage GitHub secrets. |
| `toolkit credentials delete-gh-secret` | Delete a single GitHub secret. |
| `toolkit credentials extract-common` | Extract shared infrastructure secrets into common.enc.yaml. |
| `toolkit credentials generate` | Generate all primary authentication credentials (Authelia and Basic Auth). |
| `toolkit credentials hash-password` | Interactively prompts for a password, generates its Argon2 hash, and updates the specified key in the SOPS-encrypted secrets file. |
| `toolkit credentials init-env` | Initialize a new environment's SOPS file and generate service secrets. |
| `toolkit credentials list-gh-secrets` | List all configured secrets in the GitHub repository. |
| `toolkit credentials reconcile-grafana-admin` | Detect (and optionally fix) Grafana's admin row drifting from its break-glass declaration. |
| `toolkit credentials set-gh-secret` | Set a single GitHub secret. |
| `toolkit credentials setup-gh-secrets` | Sync environment configuration to GitHub repository secrets. |
| `toolkit credentials show` | Decrypt and display secrets from SOPS-encrypted file. |
| `toolkit dashboard` | Interactive terminal dashboard. |
| `toolkit deployment` | High-level deployment orchestration (setup, deploy, rollback). |
| `toolkit deployment image-tag` | Print the immutable ``sha-<short>`` tag pinned for a platform app (ADR-056 build-once). |
| `toolkit deployment promote` | Promote an app to an immutable image tag (ADR-046 D6). |
| `toolkit info` | Show toolkit information and configuration. |
| `toolkit infra` | Infrastructure deployment and status commands |
| `toolkit infra ansible` | Ansible management commands |
| `toolkit infra ansible generate` | Generate Ansible inventory from common.yaml (SSOT). |
| `toolkit infra ansible run` | Run an Ansible playbook against an inventory generated for this run. |
| `toolkit infra ansible syntax-check` | Parse every playbook without running it — the Ansible half of `make lint`. |
| `toolkit infra argo` | Argo CD hub management (targetRevision swap, etc.) |
| `toolkit infra argo check-drift` | Compare live Argo CD Applications against their git manifests (#1016). |
| `toolkit infra argo check-spokes` | Probe every spoke with the credential THE HUB stores (#1277). |
| `toolkit infra argo check-window` | Refuse while any Application holds a restore window (BACKUP-070). |
| `toolkit infra argo hub-pause` | Stop ONE hub reconciling, without removing anything it holds. |
| `toolkit infra argo hub-resume` | Resume a paused hub — the rollback for `hub-pause`. |
| `toolkit infra argo set-revision` | Patch an Argo CD Application's spec.source.targetRevision. |
| `toolkit infra argo spoke-url` | Print one spoke's K3s apiserver URL, resolved from the SSOT (#1215). |
| `toolkit infra argo unregister-spoke` | Detach ONE hub from ONE spoke, without pruning the spoke. |
| `toolkit infra headscale` | Headscale VPN ACL policy + mesh probe (ADR-041) |
| `toolkit infra headscale policy-check` | Render policy.hujson from the SSOT and validate it with `headscale policy check` (Docker). |
| `toolkit infra headscale probe` | Probe the preserved mesh flows after a policy reload (auto-revert gate, ADR-041). |
| `toolkit infra headscale recycle-stale` | Reclaim a canonical node name from a dead record after a preemption (#1369). |
| `toolkit infra k8s` | Kubernetes management commands |
| `toolkit infra k8s access` | Cluster-access transport (ADR-052): bring up/tear down/inspect the local->apiserver tunnel |
| `toolkit infra k8s access connect` | Bring up the cluster-access transport (idempotent). |
| `toolkit infra k8s access disconnect` | Tear down the cluster-access transport (idempotent; no-op for prod). |
| `toolkit infra k8s access status` | Report whether the transport is up and which transport was resolved. |
| `toolkit infra k8s alert-smoke` | Prove the certificate-alerting path still works, end to end (OBS-007). |
| `toolkit infra k8s apply-middleware-secrets` | Render Traefik Middleware CRDs from templates + SOPS, then kubectl apply. |
| `toolkit infra k8s apply-secrets` | Decrypt SOPS secrets and apply as K8s Secrets. |
| `toolkit infra k8s bootstrap` | Apply ONLY the cluster-wide bootstrap layer (cluster_bootstrap SSOT) — ADR-047 / TOOL-009. |
| `toolkit infra k8s deploy` | Deploy K8s manifests to the cluster. |
| `toolkit infra k8s dry-run` | Generate manifests and validate with dry-run (no apply). |
| `toolkit infra k8s fetch-kubeconfig` | Fetch a cluster's kubeconfig with a transport-agnostic server (ADR-052). |
| `toolkit infra k8s provision-postgres-tenant` | Idempotently provision a tenant role and database in PostgreSQL (infra.postgres). |
| `toolkit infra k8s render-apply` | Render RESOLVE_* placeholders (MagicDNS) in a single manifest, then server-side apply. |
| `toolkit infra k8s restart` | Restart any K8s deployment (rollout restart + wait) on the env's cluster. |
| `toolkit infra k8s status` | Show K8s resource status for the kubelab namespace. |
| `toolkit infra n8n` | n8n workflow import (TOOL-009) + notification-fabric smoke (NOTIFY-001) |
| `toolkit infra n8n import` | Reconstruct the n8n workflow + Header Auth credential from Git + SOPS (TOOL-009). |
| `toolkit infra n8n probe` | Probe the public n8n webhooks end to end (APP-CONFIG-015 AC4/AC5). |
| `toolkit infra n8n smoke` | Smoke-test the notification fabric end to end (NOTIFY-001). |
| `toolkit infra node` | Node-level recovery that must work when Ansible cannot reach the host (OPS-024) |
| `toolkit infra node reclaim` | Remove the buildx builders and CI job volumes a full disk leaves no other way to clear. |
| `toolkit infra nuke` | DESTROY EVERYTHING: Stops containers, removes volumes, networks, and cleans caches. |
| `toolkit infra status` | Check the status of infrastructure services (e.g., Traefik). |
| `toolkit infra terraform` | Terraform management commands |
| `toolkit infra terraform gcp-recreate` | Delete the running hub and let the MIG rebuild it — a preemption on demand. |
| `toolkit infra terraform gcp-resize` | Set the MIG's target size. 0 stops paying for the VM; 1 boots a fresh one. |
| `toolkit infra terraform gcp-status` | Describe the hub's managed instance group. Read-only. |
| `toolkit infra terraform killswitch-prove` | Prove the billing kill switch fires, end to end (AC2b). |
| `toolkit infra terraform run` | Run one Terraform action against one root (TF-007). |
| `toolkit infra terraform state-bootstrap` | Create the state bucket, its history lock rule and its token (TF-007). Idempotent. |
| `toolkit infra terraform verify-killswitch` | Prove the billing kill switch fires, against a scratch project (AC2b). |
| `toolkit infra vps` | The prod VPS as Hetzner sees it: snapshots (PREP-002) |
| `toolkit infra vps snapshot` | Snapshot the VPS through the Hetzner API: the rollback of last resort (PREP-002). |
| `toolkit monitoring` | Uptime Kuma monitoring: status and config-as-code (backup is node_backup) |
| `toolkit monitoring apply` | Declarative sync: apply monitors from seed JSON to Uptime Kuma. |
| `toolkit monitoring bootstrap` | Full disaster recovery: create admin user + import monitors. |
| `toolkit monitoring export` | Export monitors and notifications to JSON (config-as-code). |
| `toolkit monitoring import` | Import monitors from JSON seed files into Uptime Kuma. |
| `toolkit monitoring status` | Check Uptime Kuma connectivity and container status on RPi3. |
| `toolkit obs` | Agentic Observability & SRE triage commands (Loki, Grafana, Slack). |
| `toolkit obs alerts` | List active Grafana alerts and their firing states. |
| `toolkit obs drill-pvc-unbound` | Prove `obs015-pvc-unbound-failure` fires, and remove the claim afterwards. |
| `toolkit obs logs` | Query Loki logs with LogQL filtering and traceback deduplication. |
| `toolkit obs slack` | Read or post messages to Slack incident channels. |
| `toolkit obs triage` | Execute the 4-step automated SRE triage pipeline. |
| `toolkit obs watcher-run` | Run a CronJob once now, print its log, and delete the Job. |
| `toolkit product` | Validate and render kubelab.yaml product contracts (ADR-067). |
| `toolkit product render` | Render a contract into apps.platform.<app>; without a flag, print the contract-owned keys. |
| `toolkit product validate` | Validate a product contract against the schema, and with --registry against the platform; exit 1 if refused. |
| `toolkit registry` | Container registry maintenance (tag pruning). |
| `toolkit registry prune` | Prune ephemeral image tags (ADR-046). |
| `toolkit secrets` | Unified secrets management (SOPS vaults, K8s secrets, audit). |
| `toolkit secrets acme-token-scope` | Ask Cloudflare what the ACME DNS-01 token may do on each issuing zone (#2459). |
| `toolkit secrets apply` | Decrypt SOPS secrets and apply as K8s Secrets to the cluster. |
| `toolkit secrets audit` | Audit secrets completeness across environments. |
| `toolkit secrets catalog` | List all secrets in the catalog with descriptions. |
| `toolkit secrets check-expiry` | Ask the issuing services when the provider-issued credentials expire. |
| `toolkit secrets edit` | Open the SOPS-encrypted secrets file in your editor. |
| `toolkit secrets hash` | Generate Argon2 hashes for all OIDC client secrets. |
| `toolkit secrets init` | Generate machine-generable secrets (random tokens, hex keys, RSA). |
| `toolkit secrets jwks` | Generate OIDC JWKS RSA 4096 key and store in SOPS vault. |
| `toolkit secrets preauth-keys` | Report the tailnet admission tickets that are still live, and expire the ones you name. |
| `toolkit secrets rotate` | Rotate ONE credential, and stop before the cluster. |
| `toolkit secrets set` | Set a secret value in the SOPS vault. |
| `toolkit secrets show` | Decrypt and display a secret from the SOPS vault. |
| `toolkit secrets sync-secret-manager` | Deliver the GCP hub's boot secrets to Google Secret Manager (one-way). |
| `toolkit secrets unset` | Remove a key from the SOPS vault. |
| `toolkit services` | Manage services and applications |
| `toolkit services build` | Build application using docker compose. |
| `toolkit services clean` | Clean application artifacts and resources. |
| `toolkit services down` | Stop one or more services or applications. |
| `toolkit services gitea` | Reconcile the Gitea forge against its declaration |
| `toolkit services gitea actions-secrets` | Deliver catalog-declared Actions secrets from SOPS to forge repositories (TOOL-062). |
| `toolkit services gitea drop-empty` | Remove an EMPTY DECLARED repository, so a migration can create it in its place. |
| `toolkit services gitea git` | Run `git` against the forge over HTTPS as its admin (break-glass credential). |
| `toolkit services gitea issue` | Issues on the forge |
| `toolkit services gitea issue create` | Open an issue as the same authoring identity as `pr create` (TOOL-078). Prints `#<number> <url>`. |
| `toolkit services gitea pr` | Pull requests on the forge (open only; merging stays a human action) |
| `toolkit services gitea pr create` | Open a pull request as the identity `gitea git` pushes with (TOOL-078). |
| `toolkit services gitea prune-runners` | Deregister Actions runners the declaration does not name. |
| `toolkit services gitea reconcile` | Create declared organizations and repositories in Gitea; report undeclared ones. |
| `toolkit services gitea rotate-token` | Revoke a Gitea machine token and clear its SOPS key so a re-provision re-mints it. |
| `toolkit services gitea token-scopes` | Check each machine token's MINTED scopes against its declared grant (TOOL-056, #1551). |
| `toolkit services health` | Check health of running services using config-driven endpoints. |
| `toolkit services list` | List all available services and applications. |
| `toolkit services logs` | Show logs for one or more services or applications. |
| `toolkit services push` | Push Docker image for an application to registry. |
| `toolkit services restart` | Restart one or more services or applications (down + up). |
| `toolkit services up` | Start one or more services or applications. |
| `toolkit services vikunja` | Audit the Vikunja task platform |
| `toolkit services vikunja audit-users` | List every Vikunja account, separating password signups from OIDC logins. |
| `toolkit sync` | Sync generated files from SSOT (common.yaml, SOPS). |
| `toolkit sync all` | Run all sync operations. |
| `toolkit sync branding` | Sync IDP brand CSS from common.yaml SSOT. |
| `toolkit sync images` | Sync K8s image tags from common.yaml to kustomization.yaml. |
| `toolkit sync oidc` | Generate the OIDC client files from the SSOT and the stored SOPS digests (SSOT-017). |
| `toolkit sync operators` | Refresh vendored cluster_bootstrap operator manifests from their SSOT version (ADR-047). |
| `toolkit sync platform-json` | Sync public platform.json manifest from common.yaml SSOT (issue #1347). |
| `toolkit sync r2-watcher-targets` | Render the R2 watcher's per-node targets from backup.sources (BACKUP-055). |
| `toolkit sync terraform-backend` | Render the shared Terraform backend settings from terraform.state (TF-007). |
| `toolkit sync vikunja` | Sync the declared Vikunja projects, team, shares and labels idempotently. |
| `toolkit tools` | Development tools and utilities |
| `toolkit tools branch-protection` | Reconcile GitHub branch protection with `ci.branch_protection` in common.yaml. |
| `toolkit tools certs` | TLS certificate management for local development |
| `toolkit tools certs generate` | Generate TLS certificates for local development using mkcert. |
| `toolkit tools certs install-mkcert` | Install mkcert tool for generating locally-trusted certificates. |
| `toolkit tools certs status` | Show certificate status for an environment. |
| `toolkit tools cli-reference` | Keep the README's command table equal to the command tree it describes. |
| `toolkit tools delivery-health` | Refuse a delivery workflow whose newest run never started. |
| `toolkit tools lessons-index` | Order each category's lesson rows newest first (by date, then by number within a date, #1912), after refusing a corpus a rewrite would hide. |
| `toolkit tools mutate` | Run the test unmutated, apply one replacement, run it again, restore the file. |
| `toolkit tools review-attestation` | Report whether a PR was actually reviewed, and refuse it if not. |
| `toolkit tools spec-gate` | Refuse a PR that closes a spec's issue without archiving the spec. |
| `toolkit version` | Show version and exit. |

<!-- cli-reference:end -->
