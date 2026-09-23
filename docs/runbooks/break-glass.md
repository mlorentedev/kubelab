# Break-glass: getting in while Authelia is down

> ADR-062 D4, AUTH-004 AC7. Exceptional by design: every use pages the operator
> channel, and every used credential is rotated afterwards.

## The rule

The emergency path shares no dependency with the normal one. It never crosses the
public router (Traefik) or the IdP (Authelia). It goes over the private network:

- a **port-forward** to the service, when it runs in the cluster;
- its **EndpointSlice address over the tailnet**, when it runs outside (Gitea on the Beelink);
- the **cluster credential** itself, where no application account is used (Argo CD, Authelia).

One consequence worth knowing: Grafana's public route carries the `authelia`
ForwardAuth middleware. It strips `Authorization` and fails closed with the IdP
down, so a "local login on the public URL" could never be a break-glass there.
The private path does not touch it, which is why that second lock stays.

## What you need, and must keep off the laptop too

- Tailscale on the workstation (the tailnet is Headscale on the VPS, not Authelia).
- `~/.kube/kubelab-{staging,prod,hub}-config`: certificate kubeconfigs, independent of any IdP.
  The prod one uses the VPS public IP, so it works without the tailnet.
- The SOPS age key. An offline copy off the laptop exists (confirmed by the operator, 2026-09-23).

## Use

```bash
make break-glass SVC=<service> ENV=<staging|prod>            # opens the path, pages the channel
make break-glass SVC=<service> ENV=<env> DRY_RUN=1           # only shows the path; opens and announces nothing
```

The command prints the way in, the user, and the `make secrets-show ...` to run
**in your own terminal** for the password. It never prints the password itself.
It exits `3` for a service whose declaration is `none` (no break-glass, on
purpose) and `1` for a service that does not depend on Authelia (its normal login
is unaffected).

Which services exist here is not listed in this runbook on purpose: it is derived
from the rendered routes and declared in `apps.services.security.authelia.break_glass`
(`infra/config/values/common.yaml`). Run the command with a wrong name to get the
current list.

### Argo CD

`cluster: hub`. With `KUBECONFIG=~/.kube/kubelab-hub-config`, use `kubectl -n argocd`
or `argocd --core --kube-context <ctx>`: the CLI then talks to the Kubernetes API
under Kubernetes RBAC, with no Argo CD server login.

### Gitea

`manu` with its local password, over the private URL (plain HTTP to the Beelink, carried
inside the tailnet's WireGuard), by API or `git`.
The web form is not relied on. For credential repair, see
[gitea-credential-recovery.md](gitea-credential-recovery.md).

### Authelia itself

`KUBECONFIG=~/.kube/kubelab-<env>-config kubectl -n kubelab ...`: logs, rollout
restart, or `make flush-sessions ENV=<env>` after a secret rotation.

## After every use

1. Rotate the accounts: `toolkit secrets rotate --group break-glass --env <env>`. It changes
   each service, verifies the new password with a login, and restores everything if a step
   fails. Then commit the changed `*.enc.yaml` in a PR at once, because the services already
   hold the new values, and run `make apply-secrets ENV=<env>`.
2. Record the use and its cause on the incident ticket.

## Drill

Quarterly (#1211). `toolkit auth drill-idp-down --env staging` is the next AUTH-004 AC7
task and does not exist yet. It will scale Authelia to 0, open every declared path, and
restore Authelia in a `finally`. Until it lands, `DRY_RUN=1` on every service is the
cheap check that the paths still resolve.
