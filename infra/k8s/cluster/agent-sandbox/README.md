# agent-sandbox (vendored)

Kubernetes runtime substrate for iris (SDD-034c). A cluster-scoped operator applied
OUTSIDE the Argo CD overlay by the toolkit (ADR-047 / TOOL-009), declared in the
`cluster_bootstrap` list in `infra/config/values/common.yaml`.

- **Upstream:** <https://github.com/kubernetes-sigs/agent-sandbox>
- **Release:** `v0.5.0rc1` (pre-release; core API graduated to `v1beta1`)
- **Asset:** `manifest.yaml` — the official single-file install, vendored verbatim.
- **Provides:** the `sandboxes.agents.x-k8s.io` CRD (Kind `Sandbox`, `v1beta1`), the
  `agent-sandbox-controller` Deployment + RBAC, and the `agent-sandbox-system` namespace.
- **Image:** `registry.k8s.io/agent-sandbox/agent-sandbox-controller:v0.5.0rc1`

## Refresh

Do NOT hand-edit `manifest.yaml`. Bump the `version` of the `agent-sandbox` entry in
`infra/config/values/common.yaml`, then run:

```sh
make sync-operators
```

which re-downloads the pinned release asset deterministically (TOOL-009 T6). The file is
vendored verbatim so that `git diff --exit-code` after a no-op sync stays clean.

## Not vendored

The release also ships `extensions.yaml` (`SandboxClaim` / `SandboxTemplate` /
`SandboxWarmPool` under `extensions.agents.x-k8s.io`, plus an extensions controller). iris
conformance exercises only the core `Sandbox` CR, so the extensions are intentionally out
of scope. Add them as a second `cluster_bootstrap` entry if warm pools are needed later.

## Lint

This directory is excluded from yamllint (`.pre-commit-config.yaml`) — it holds pinned
third-party manifests whose formatting we do not own.
