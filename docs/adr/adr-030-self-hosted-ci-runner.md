---
id: adr-030-self-hosted-ci-runner
type: adr
status: active
created: "2026-03-29"
---

# ADR-030: Self-Hosted CI Runner on Beelink

## Status

**Accepted** — 2026-03-30

## Amendment — 2026-06-26 (hosted-primary for the public repo)

Two assumptions behind the original decision no longer hold:

1. **Cost / "zero Actions minutes."** The repo is now **public**, so GitHub-hosted runners are **free and effectively unlimited in parallelism**. The cost driver that motivated self-hosted is gone.
2. **"No pushes happen when the homelab is off, so no workflow triggers without a runner."** The ADR-053 cross-repo flow broke this: `web` pushes fire a `repository_dispatch` → the **Web Image Receiver** and downstream workflows run on `master` independently of any local dev session. Combined with the single runner (the documented "jobs serialize" negative), this produced exactly the predicted failure — a backlog of ~9 runs serialized behind one ~12-min Docker build, with even cheap `validate`/drift jobs queued behind it.

**Resolution — flip the default to GitHub-hosted; self-hosted becomes opt-in.**

- `RUNNER_DOCKER` set to `["ubuntu-latest"]` (unset → identical fallback). Every workflow already reads `fromJSON(vars.RUNNER_DOCKER || '"ubuntu-latest"')`, so this one change routes the whole fleet to hosted runners — many concurrent jobs, free, no homelab dependency. An audit confirmed **no CI job needs homelab access**: all are portable (buildx → Docker Hub with `cache-from: type=gha`, Python toolkit, `gh`/`git` PR-opening, release ZIP). The two greps that matched homelab patterns were a comment and Release-body text, not steps.
- **Concurrency cancellation** added to the PR-triggered workflows (`ci.yml`, `check-config-drift.yml`): a new commit cancels the superseded run instead of piling onto the fleet.
- The self-hosted runner (`kubelab-bee`) **stays available**: re-enable it for any future job that genuinely needs homelab resources (a step that must reach the cluster or a LAN-only service) by setting `RUNNER_DOCKER` back to the self-hosted labels, or per-job. The fork-PR guard and the toggle mechanics below are unchanged.

The original self-hosted rationale remains valid for a **private** repo or a homelab-bound job; this amendment changes only the *default* for the current public, GitOps-delivered repo.

## Context

All CI/CD workflows ran on GitHub-hosted runners (`ubuntu-latest`), consuming GitHub Actions minutes and depending on shared infrastructure. With Beelink provisioned as the on-demand Platform Node (ADR-028), we have dedicated compute (8GB RAM, 4 cores) already running a GitHub Actions runner container (ANSIBLE-013).

Key drivers:
- **Cost**: GitHub Actions free tier has 2000 min/month limit. Self-hosted is unlimited.
- **Control**: Dedicated resources, no queue wait, persistent build cache.
- **Architecture**: Beelink is always on when developing. No pushes happen when homelab is off, so no workflows trigger without a runner available.

## Decision

### Runner routing via `fromJSON` + repo variable

All 6 CI workflows use dynamic runner selection:

```yaml
runs-on: ${{ fromJSON(vars.RUNNER_DOCKER || '"ubuntu-latest"') }}
```

- **`RUNNER_DOCKER` not set** → `ubuntu-latest` (safe default)
- **`RUNNER_DOCKER` = `["self-hosted","linux","docker"]`** → Beelink runner

Reusable workflows (`ci-pipeline`, `ci-publish`) receive `runner` as an input parameter from callers. Standalone workflows read `vars.RUNNER_DOCKER` directly.

This is the GitHub-recommended pattern for hybrid runner fleets. Single toggle, explicit, auditable.

### Security model: fork PR guard

Self-hosted runner mounts Docker socket (`/var/run/docker.sock`), giving jobs host-level access. Fork PRs could exploit this to access the internal network.

Mitigation: PR-triggered workflows force fork PRs to GitHub-hosted:

```yaml
runs-on: >-
  ${{ github.event.pull_request.head.repo.fork
      && 'ubuntu-latest'
      || fromJSON(vars.RUNNER_DOCKER || '"ubuntu-latest"') }}
```

Push-triggered workflows (release, global bundle) are safe — only trusted code reaches `master`.

Additional hardening: GitHub Settings → Actions → General → "Require approval for all external contributors".

### Resource allocation

Beelink (8GB total):

| Service | CPU Limit | RAM Limit | CPU Reserved | RAM Reserved |
|---------|-----------|-----------|--------------|--------------|
| GH Runner | 4.0 | 6G | 1.0 | 2G |
| MinIO | 0.5 | 512M | 0.1 | 128M |
| Glances | 0.25 | 256M | 0.1 | 64M |
| OS + Docker | — | ~1.2G | — | — |

Runner container limits only affect the runner process itself. Docker builds use the host directly via socket mount (not constrained by container limits).

### Tool cache persistence

Ephemeral runner (`EPHEMERAL: 1`) recreates the container after each job. To avoid re-downloading Go/Node toolchains every job, a persistent volume is mounted:

```yaml
volumes:
  - runner_toolcache:/opt/hostedtoolcache
```

`actions/setup-go` and `actions/setup-node` cache toolchains in `/opt/hostedtoolcache`, surviving container restarts.

### Multi-arch builds

`docker/setup-qemu-action@v3` added explicitly to `ci-publish.yml`. Previously implicit (GitHub-hosted runners have QEMU pre-installed). Now portable across both runner types.

Buildx builder managed by `docker/setup-buildx-action@v3` per-job (idempotent, self-contained). Ansible also maintains a `multiarch` builder on the host for manual builds.

## Consequences

### Positive
- Zero GitHub Actions minutes consumed for all CI/CD
- Faster builds (persistent tool cache, local Docker layers)
- Full control over runner environment and resources
- Single repo variable toggle for rollback to GitHub-hosted

### Negative
- Single runner = jobs serialize (no parallelism for multi-app PRs)
- Runner availability depends on Beelink being powered on
- Docker socket access requires security vigilance (fork guard)

### Risks
- If Beelink is off and a workflow triggers (e.g., dependabot), jobs queue indefinitely. Mitigation: set `RUNNER_DOCKER` back to unset or monitor queued jobs.
- Runner container OOM under heavy builds. Mitigation: 6GB limit with 2GB headroom.

## Operations

### Toggle runner

```bash
# Activate self-hosted
gh variable set RUNNER_DOCKER --body '["self-hosted","linux","docker"]'

# Fallback to GitHub-hosted
gh variable delete RUNNER_DOCKER
```

### Verify runner

```bash
# Check which runner executed a job
gh run view <RUN_ID> --log 2>&1 | grep "Runner name"
# "kubelab-bee" = self-hosted, "GitHub Actions X.Y.Z" = GitHub-hosted

# Runner container logs on Beelink
ssh deployer@100.64.0.3 "docker logs github-runner --tail 50"
```

### Update resources

Resources defined in SSOT (`infra/config/values/common.yaml`):
- `apps.services.automation.github_runner.resources.*`
- `apps.services.data.minio.resources.*`
- `apps.services.observability.glances.resources.*`

Apply: `make provision NODE=bee ENV=staging`

## References

- PR #161: Implementation
- ADR-028: Operational topology (Beelink as on-demand platform node)
- ANSIBLE-013: Beelink provisioning (runner container setup)
- ANSIBLE-015: CI workflow integration (this ADR's implementation)
