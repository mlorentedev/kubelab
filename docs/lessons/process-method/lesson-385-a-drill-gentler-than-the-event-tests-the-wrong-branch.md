---
id: lesson-385-a-drill-gentler-than-the-event-tests-the-wrong-branch
type: lesson
status: active
created: "2026-08-24"
owner: manu
category: process-method
tags: [kubelab, process-method, verification, spec, incident]
---

# A drill gentler than the event it stands for exercises the branch that works

**Context**: GCP-001's AC4 demanded evidence of self-healing after preemption,
and was explicit about not accepting a screenshot: *"a real simulated preemption,
not a MIG config screenshot"*. It was demonstrated twice — once by a template
change, once by `gcloud compute instances delete` — and passed both times.

**Problem**: the first genuine preemption falsified it. Both demonstrations were
**graceful** terminations, where the node logs out on the way down and its
Headscale record flips offline promptly. The recovery path branches on that, so
the drills exercised the branch that works and never touched the one that runs
when a machine is killed outright. The criterion was satisfied, the acceptance
was honest, and the claim was still wrong.

Three weaker forms of the same mistake showed up within the same day:

- **A drill command that reports success without acting.**
  `gcloud compute instances simulate-maintenance-event` returned `DONE` with the
  instance still RUNNING and its `creationTimestamp` unchanged. Taken at face
  value it would have "proved" a rebuild that never happened.
- **A control that returns the same signal as the real attempt** — the shape
  already recorded in lesson-382.
- **A monitor whose text asserts one of the two causes it can fire for**
  (lesson-386).

**Solution**: pick the trigger by asking *what does the real event present to the
system that recovers it*, not by what is convenient to run. A preemption on a
Spot VM in a MIG manifests as the instance entering STOPPING, so
`gcloud compute instances stop` puts the MIG in front of the identical condition
— and GCP's operation log proves the equivalence rather than assuming it: both
produce `Instance eligible for repair: instance should be RUNNING, but is
STOPPING.` With matching stimulus the fix was observed end to end, unattended.

**Rule**: state the stimulus a drill applies and argue that it matches the event,
in the same breath as the result. "Demonstrated" without that argument is an
assertion about the easiest reachable path. An independent reviewer graded this
spec on exactly that and was right to — the verdict was FAIL on a criterion whose
box was already ticked.

**Tags**: `#verification` `#drills` `#spec` `#adversarial-review` `#issue-1369`
