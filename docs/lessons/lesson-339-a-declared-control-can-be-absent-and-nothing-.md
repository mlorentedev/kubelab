---
id: lesson-339-a-declared-control-can-be-absent-and-nothing-
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson, docker, ansible, cgroups, healthcheck, verification, gotcha]
---

# A declared control can be absent, and nothing will say so

**Context:** 2026-08-15. Three unrelated defects surfaced in one session, on three different mechanisms, and only after the third did the shape become obvious.

1. **A memory limit the kernel discarded.** `common.yaml` declared `memory_limit: 256M` for Glances on the RPi3, the role rendered it, the deployed compose file carried it, and `docker inspect` reported `HostConfig.Memory=0`. The memory cgroup controller was absent from that kernel, so Docker dropped the limit — while applying the **CPU limit from the same compose block** (`NanoCpus=250000000`). (#1101)
2. **A healthcheck that could never execute.** CoreDNS on the RPi4 reported `unhealthy` with a FailingStreak of **996**. The probe was `["CMD", "dig", ...]` and `coredns/coredns` is distroless — no shell, no `dig`. It had never passed once. (#1108)
3. **A published port that was never published.** Glances containers ran with `HostConfig.PortBindings` requesting `100.64.0.3:61208` and `NetworkSettings.Ports` empty. Docker started them before tailscaled had put the address on the interface, so `docker-proxy` could not bind and the port was dropped silently. Five of seven monitoring endpoints were unreachable from the dashboard scraping them. (#1115)

**The trap:** in every case the *declaration* was correct and reviewable. The compose file said 256M. The healthcheck was in the template. The port was in `ports:`. Reading the configuration — which is what review, linting and `git diff` all do — confirms the intent every time and can never observe the effect.

Worse, each had camouflage:

- The CPU limit from the same stanza **did** apply, so any spot check that happened to look at CPU confirmed "limits work".
- The neighbouring Pi-hole healthcheck used the same `dig` and was genuinely green, so one red beside one green reads as a known-bad service rather than a broken probe.
- `docker ps` reported the portless containers `Up`, and a crashed container would have been *more* visible than a healthy-looking one serving nothing.

None of them self-heal, for the same underlying reason: **container attributes are fixed at create time**, and `docker compose up -d` compares the compose spec hash, which had not changed. `restart: unless-stopped` re-runs the same wrong container. So each defect survived every restart and reboot until someone compared the two sides by hand.

**Fix:** compare the declared value against the enforced one, in the role that declares it, and recreate on divergence.

```yaml
- name: Read the limit currently applied to the container
  command: docker inspect glances --format '{{.HostConfig.Memory}}'
  register: _applied
  changed_when: false
  failed_when: false

- name: Detect drift between the declared and the applied value
  set_fact:
    _drift: "{{ (_applied.stdout | trim | int) != (glances_memory_limit | human_to_bytes) }}"

# ...then fold `_drift` into the --force-recreate condition.
```

For ports the same idea reads `{{len .HostConfig.PortBindings}}:{{len .NetworkSettings.Ports}}` — requested versus in effect. Both shipped in the `glances` role; generalising them across every compose role is #1104.

**Rule:**
- **A configuration file is a request, not a state.** Verify the state, and prefer a check that reads it back from the thing that enforces it — the kernel, the daemon, the cluster.
- **Two-sided controls only.** When a test can only fail one way, it cannot distinguish "working" from "not running at all". The cgroup fix was only believable once 300MB under a 64M cap died with exit 137 **and** 32MB under the same cap survived.
- **Suspect an implausibly good result.** A memory sweep reporting that restic survived a 16M cap was the tell; a Go runtime alone exceeds that. The cap was a silent no-op, and the sweep had been measuring nothing.
- **A probe that has never passed is worse than no probe.** It is indistinguishable from a service that has never worked, so the one real outage it exists to catch arrives at an indicator that was already red.

**Tags:** `#docker` `#ansible` `#cgroups` `#healthcheck` `#verification` `#gotcha`
