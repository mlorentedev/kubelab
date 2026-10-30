---
id: ANSIBLE-086-rootless-download-attempts
type: spec
status: active
created: "2026-10-30"
owner: manu
issue: "kubelab#2834"
---
# ANSIBLE-086: Rootless download attempts

## Intent

Behind the lab edge a pull's connections end in `unexpected EOF` about every 10 minutes. dockerd resumes a layer on each of its own attempts and drops every layer once a layer runs out of them. #2835 gave the system daemon 40 attempts. agent_stack's rootless daemon, which holds the hermes-kubelab images (4.5 GB and 1.6 GB), reads its own `daemon.json`, and nothing renders one, so it keeps Docker's 5. The include that sizes pulls also misjudges them: it bounds an attempt by transfer time alone, while dockerd can sleep up to 65 minutes between its 40 attempts, and its estimate assumes a pull gets all of `down_kbit`, when the Open WebUI refill got 54% of it (#2703).

## Scope

In:

- `networking.edge.uplink.max_download_attempts` (40) and `networking.edge.uplink.bandwidth.pull_goodput` (0.54) in `common.yaml`, the names the operator chose.
- Every play that runs the docker role or agent_stack sets `docker_max_download_attempts` from the first key. The docker role renders it into `/etc/docker/daemon.json`, and agent_stack into the agent user's `daemon.json`, then reloads that daemon and reads the reload event to confirm the value.
- Every play that sets `image_pull_down_kbit` sets `image_pull_goodput` from the second key. Where its node's daemon is the docker role's, it also sets `docker_max_download_attempts`. The include divides its estimate by the goodput, and adds dockerd's pause budget, `5·n(n−1)/2` seconds, to the attempt bound.

Out:

- rpi3's daemon, which no role configures, so it keeps Docker's 5 attempts. Filed as a ticket.
- The goodput for `apt` downloads (`_includes/apt-upgrade.yml`). It was measured for a registry pull.
- Moving the system daemon from restart to reload. Its other keys need a restart.

## Checklist

- [ ] Failing tests first: the attempts value read from `common.yaml` and held to 37–… by the pause bound; both daemons render the play var; every docker-role and agent_stack play sets it from the key; every sized play sets the goodput; the bound covers the pause budget; the estimate divides by the goodput and states it.
- [ ] `common.yaml` keys, play vars, docker role, agent_stack copy + reload + event check, include.
- [ ] Mutants red: a play that drops a var, a role that renders a literal, the include without the pause term or the goodput.
- [ ] `make provision NODE=ace2 ENV=prod TAGS=agent_stack`: the file exists, the reload event reads 40, hermes containers' `StartedAt` unchanged; a rerun reports `changed=0`.

## Evidence

See the PR body.

## Next

Implement.

## Promotion candidates

- [ ] Lesson? Decide at the end: a rootless daemon reads its own `daemon.json`, and a reload is proved by the daemon's own event, not by the unit.
- [ ] ADR? `no`
- [ ] Pattern? `no`
