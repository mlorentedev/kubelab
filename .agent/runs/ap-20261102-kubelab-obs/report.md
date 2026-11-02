# Run ap-20261102-kubelab-obs

Armed 2026-11-02T05:55Z, expires 17:55Z. Envelope: `.agent/unattended.yml` at f951fc7.
Paused 06:05Z-07:10Z by a usage limit; the wake-lock held.

## Items

- #2929 OBS-042: spec opened with `--over-wip-limit`. PR 1 (notice title, cause, runbook) is #2987, draft, proven by delivery from a local grafana-oss:13.0.2.
- #2924: attribution read from prod Grafana's state history: none of the eight pages was a Grafana rule (comment on the issue). The record gap is at Apprise, for the other senders.
- #2921 AI-030: fix committed on `fix/ai-030-vault-mirror-fail-fast`; provisioning ace2 from the branch.

## Prod and staging reads

- 05:58Z kubectl get deploy (staging grafana, apprise; prod grafana image): reachability check only.
- 07:05Z `make alerts ENV=staging`: nothing firing.
- 07:40Z prod Grafana `/api/annotations?type=alert`, 2026-10-26..11-02, through the toolkit's port-forward and read-only alerts token.

## Prod changes

- `make provision NODE=ace2 ENV=prod TAGS=agent_stack` from the #2921 branch (the tag also runs `node_maintenance`, which the playbook files under it).
