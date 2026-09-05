---
id: lesson-431-a-cgroup-limit-does-not-reach-what-the-bounded-process-starts
type: lesson
status: active
created: "2026-09-04"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, gitea-actions, act-runner, cgroups, tool-035]
---

# A cgroup limit does not reach what the bounded process starts

**Context**: Asking whether `gitea_runner.capacity` could go from 2 to 3 on the
Beelink, which also hosts Gitea itself. The declaration in `common.yaml` had
already refused once, on arithmetic, and had written down the condition for
revisiting: *"nothing has ever executed this workflow on this hardware, so
`build-pdf`'s actual footprint is unknown."* Four pull requests running six jobs
each finally made that measurable.

**Problem**: The measurement did not answer the capacity question. It invalidated
it. Peak RSS per container, sampled every 10s through the node's own Glances API
while CI ran:

```
buildkit builder   4095M   no limit
(unnamed)          1968M   no limit    <- the workflow's own `docker create`
(unnamed)           939M   no limit
(unnamed)           587M   no limit
job:build-pdf       479M   2G limit    <- the only bounded one, at 23%
job:audit           183M   2G limit
job:test             20M   2G limit
act-runner          512M   512M limit  <- exactly at its ceiling
```

Node: 7.5G total, 5.85G available, `load1` peaking at **8.04 on 4 cores**.

**The thing that was bounded was using a quarter of its allowance, while the
unbounded siblings peaked near the size of the node.** `container_options:
"--memory=2g --cpus=2"` bounds the job container act_runner starts. Every
container that job then starts through the mounted Docker socket is created by
the daemon **on the host** — a sibling, in the host's cgroup hierarchy, with the
node's whole memory as its ceiling. `docker/setup-buildx-action` starts one such
container per job, and six had accumulated across runs because nothing removes
them.

So the capacity arithmetic was counting the wrong containers. At capacity 2 this
node is already exposed: two concurrent Docker builds can ask for more memory
than it has, and the OOM killer's first-choice victim is on a node that hosts the
forge these jobs build for. Raising capacity would have multiplied the unbounded
containers, not the bounded ones.

**Solution**: Bound what actually runs, and stop starting what does not need to
exist.

- Drop `docker/setup-buildx-action`. The daemon's integrated builder needs no
  container, and the layer-cache benefit that makes buildx attractive on GitHub
  is here a property of the **shared daemon**, not of buildx — the workflow's own
  header already made that argument when it dropped `cache-from: type=gha`.
- Give every `docker create` an explicit `--memory` / `--cpus`, declared once as
  a workflow-level variable with the measurements beside it.

**Rule**: A resource limit applies to a process and its cgroup descendants. A
container started through a mounted Docker socket is **not** a descendant — it is
a sibling created by the daemon, and it inherits nothing. So before trusting a
limit, ask *which process actually allocates the memory*, and confirm the answer
by measuring rather than by reading the declaration.

The tell is a bounded container sitting far below its limit while the node is
under pressure. That combination has only one explanation: the work is happening
somewhere the limit does not reach.

**This is the same defect as [[lesson-426]], one layer down.** That one is about
the filesystem: the job and the daemon do not share one, so a path handed to
`docker run` resolves in the wrong place. This one is about the cgroup: they do
not share that either. Both follow from a single fact — **a container started
through the socket is a sibling of the job, not a child of it** — and both were
found only by measuring the real node. Whenever a workflow reaches for that
socket, expect a third instance in some other dimension.

**Note what nearly happened**: the question asked was "can we raise capacity?",
and both plausible answers ("yes, there is headroom" / "no, the budget is tight")
would have been reasoned from the job containers' declared limits — the numbers
that turn out to describe 23% of the problem. Measuring changed the answer from a
number to a different question.

Related: [[lesson-428]] (a sample is not the population — the same discipline of
checking what was actually measured).

**Tags**: `#cgroups` `#docker` `#gitea-actions` `#act-runner` `#capacity`
