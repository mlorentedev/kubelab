---
id: renovate-gitea
type: runbook
status: active
created: "2026-11-12"
updated: "2026-11-12"
owner: manu
tags: [renovate, gitea, beelink, forge, dependencies]
---

# Renovate on the Gitea forge (IDP-036)

> Dependency PRs for the repositories the forge holds, from an hourly systemd run on the Beelink. Spec:
> `specs/IDP-036-renovate-gitea/`, ticket #1384. The GitHub side is [dependency-updates](dependency-updates.md).

## What runs

| Piece | Where |
|---|---|
| `kubelab-renovate.timer` | Beelink, `OnCalendar=hourly`, `Persistent=true`: a tick missed while the node was off runs once at the next boot |
| `kubelab-renovate.service` | `Type=oneshot`, bounded by `TimeoutStartSec=45min`, ordered after `kubelab-compose.service` |
| `/opt/kubelab/renovate-run.sh` | The wrapper: probes Gitea, then `docker run --rm` of the engine |
| `/opt/kubelab/renovate/config.yaml` | Global config: the repository list (from `gitea.organizations`) and the shared preset at the pinned tag |
| `/opt/kubelab/renovate/renovate.env` | Mode 0600. The engine image, platform, endpoint and the bot's token |

The run exists only while `apps.auth.identities.renovate` is declared and its token is in SOPS
(`apps.services.core.gitea.renovate_token`). The provision that creates the account mints the token and
installs nothing; the next `make provision NODE=bee ENV=prod` installs the timer, pulls the engine and starts
the timer. Remove the identity and the next provision stops and disables the timer.

The engine image and version come from `ci-workflows`' `renovate/engine.json` at `ci.renovate.preset_tag`;
bump that one tag and the next provision moves both.

## Run it on demand

No make target wraps this. On the Beelink (`ssh bee`):

```bash
sudo systemctl start kubelab-renovate.service     # blocks until the run ends
systemctl status kubelab-renovate.service         # exit status of the last run
```

`systemctl start` on a oneshot returns when the run does, which is minutes on a first run. A tick that finds
the unit still running starts nothing.

## Reading the skip line

When Gitea does not answer for 30 s the wrapper logs one line and exits 0, so the unit shows `inactive (dead)`,
not `failed`:

```
kubelab-renovate: skipped, Gitea did not answer at http://<beelink tailscale ip>:<port>/api/healthz within 30 s
```

That is the stack stopped, or still starting, on a node that is up. It is not an error: the next tick tries
again. If it persists with the stack meant to be up, read `systemctl status kubelab-compose.service` and
`docker ps` on the node. The address in the line is the one the provision verifies Gitea on, so a forge
published on no address is skipped here as well.

A **failed** unit is a different thing: the engine ran and exited non-zero, or the engine image is missing
(`--pull never`; `make provision NODE=bee ENV=prod TAGS=renovate` pulls it).

## Logs

```bash
journalctl -u kubelab-renovate.service -n 200 --no-pager
journalctl -u kubelab-renovate.service --since "1 hour ago"
```

Journald on the Beelink is persistent and capped at `journald_large_disk_max_use` (1G, set in
`provision-bee.yml`; ANSIBLE-023), so a long run's output stays readable. No journal shipper is declared for
this node, so look for the run's history on the node, not in Loki.

## Changing the memory cap

The cap is `renovate_memory_limit` in `infra/ansible/roles/beelink_services/defaults/main.yml` (`1g`), passed
to the container as `--memory`. Its peak is unmeasured: watch `docker stats kubelab-renovate` during the first
run and record the peak on #1384, then set the value from it. (The unit's own cgroup holds only the docker
client, so `systemctl status` memory figures say nothing about the engine.) Change the default in a PR and provision (`make provision NODE=bee ENV=prod TAGS=renovate`); the unit
file is re-rendered and the next run uses it. A run killed for memory fails the unit with exit status 137.

## GitHub token

Renovate reads the shared preset (`github>mlorentedev/ci-workflows//renovate/default#<tag>`) through the GitHub
API, so the run carries `GITHUB_COM_TOKEN`, delivered by `renovate.env` from
`apps.services.core.gitea.renovate_github_com_token` (prod SOPS).

**Where it comes from.** It is the same token as ci-workflows' weekly Renovate run, the Actions secret
`RENOVATE_TOKEN` in `mlorentedev/ci-workflows`, whose source is the operator's `dotf secrets` ci group (owner
decision 2026-11-12, instead of the read-only token the spec planned). It can write to the owner's GitHub
repositories, and it now also sits in `renovate.env` (0600) on the Beelink. The run is not enabled while the key
is empty: no timer is installed, and one left behind by an earlier provision is stopped.

**Record it** (value on stdin, never in the command line):

```bash
toolkit secrets set apps.services.core.gitea.renovate_github_com_token --env prod --stdin
make provision NODE=bee ENV=prod TAGS=renovate     # twice; the second reports changed=0
```

**Rotate it: both copies, together.**

1. Rotate the token in the dotf secrets ci group.
2. `dotf secrets sync ci --repo mlorentedev/ci-workflows RENOVATE_TOKEN` (the weekly GitHub run).
3. `toolkit secrets set apps.services.core.gitea.renovate_github_com_token --env prod --stdin` (the same value).
4. `make provision NODE=bee ENV=prod TAGS=renovate` (re-renders `renovate.env`).

A rotation that stops after step 2 leaves the Beelink's hourly run on a dead token, and its preset fetch fails.

**Expiry.** The catalog declares it `PROVIDER`: `make secrets-audit` ends with an "Expiry" section that asks
GitHub when the token dies (`toolkit secrets check-expiry` runs the same check alone), and warns inside the
window. A token minted with no expiry reports none.
