---
id: lesson-418-a-before-after-probe-must-be-able-to-change
type: lesson
status: active
created: "2026-09-02"
owner: manu
category: process-method
tags: [kubelab, process-method, verification, security, sec-006, monitoring]
---

# A before/after probe must be one whose state can actually change, or it passes without measuring anything

**Context**: SEC-006 put a Hetzner cloud firewall on the production VPS. Its
acceptance criterion was the strongest kind available — *verify by consequence*:
show a port outside the allow-list being refused at the cloud edge, measured from
a non-tailnet path, before and after the apply.

**Problem**: The obvious port to probe was **9000**. It is the port that caused
the whole line of work — SEC-005 (#1538) found Traefik's dashboard answering it
unauthenticated from the public internet.

It is also completely useless as a probe, and passing on it would have proved
nothing at all.

## Why the intuitive probe is the wrong one

#1541 fixed 9000 *properly*, at the Traefik layer: the service no longer listens.
So 9000 times out whether or not a cloud firewall exists. Measured before the
apply, it timed out. Measured after, it timed out. A before/after table would
have shown two identical rows and been written up as evidence.

The probe has to be a port where the two states genuinely differ. **8080** was the
only one available: Headscale publishes its control plane there on the public IP
and keeps listening regardless of any firewall. `200 OK` before, timeout after —
one measurement, and the only one that isolates the layer under test.

**The general form: a before/after measurement is only evidence if the "before"
could have been different.** When both readings are produced by something other
than the thing you are testing, the test is a tautology wearing a table.

## The same choice, twice more in one day

**Choosing the sentinel.** SEC-006 added an Uptime Kuma monitor to report
continuously that the firewall is still attached. 9000 was again the intuitive
choice and again wrong, for the same reason: it stays shut with or without the
firewall, so the monitor would be green for the wrong reason forever. 8080 works
because its *listener outlives the control being watched* — detach the firewall
and it answers again within one interval. **A canary must be a port whose process
survives what you are monitoring.**

**Misreading my own instrument.** A peer reported `argo.kubelab.live` down and
asked whether my firewall had caused it. My first probe was `curl -sI` — a HEAD
request — and it returned nothing. I was one step from reporting an outage. A
GET on the same URL returned 200 in half a second: Argo CD does not answer HEAD
usefully. The instrument was broken, not the system.

Worse, I then led my "it isn't me" reply with that 200, when the argument that
actually held was structural — the firewall declares six inbound rules and zero
outbound, so it cannot restrict an outbound connection. **I attached a sound
conclusion to the weakest evidence I had for it**, and the peer was right to say
so.

## Root cause

All three are one mistake: **reaching for the salient instrument instead of the
discriminating one.** 9000 is salient because it is the port that burned us. HEAD
is salient because it is the cheap way to check a URL. Neither can distinguish
the states in question.

Salience comes from the history of the problem; discrimination comes from the
mechanism under test. They are unrelated, and the first is much easier to reach.

## Fix

Before running a before/after check, ask: **what would make the "before" reading
different from the "after" one — and is that thing the mechanism I am testing?**
If the answer names anything else, the probe is measuring that instead.

The mechanical form of the question, which is what makes this usable rather than
merely true — **before measuring, ask what the reading would be if the change had
NOT been made. If the answer is the same, the instrument is inert, and no amount
of care recovers it.**

That is the whole diagnostic. The question is never *was I careful*, it is
**does this instrument have two possible readings in this experiment?** Care
cannot rescue a probe that returns the same value under both hypotheses.

Two supporting checks:

- **Predict the "before" reading and why.** If the prediction does not mention
  the mechanism under test, change probes. "9000 times out because Traefik does
  not serve it" never mentions a firewall.
- **Ask what a passing result rules out.** A probe that would pass under both the
  fixed and the broken world rules out nothing.

For a continuous monitor the question is the same one shifted in time: *if the
control I am watching disappeared, would this signal change?*

## Two more instances, from a different subsystem entirely

Found the same day in a parallel lane, and they matter because neither involves a
network probe — the shape is not about ports.

**An Ansible `changed` count.** Adding `GITEA__actions__ENABLED` to a compose
file when it matches Gitea's running default produces a byte-identical container,
so Docker does not recreate it. `changed=0` is the reading under *"the variable
took effect"* and equally under *"the variable was never read"*. Inert. The only
discriminating instrument is reading the value from **inside** the running
container.

**`docker ps`.** An `act-runner` container looping on a rejected registration
token reports `Up` exactly as a correctly registered one does. Container state
cannot distinguish registered from rejected; only the forge's own runner list
can.

Together with the port probes these give the same failure in three unrelated
places — a network check, a configuration-management signal, and a process
supervisor. **Salience is what makes you reach for an instrument; discrimination
is a property of the mechanism under test. The two are unrelated, which is why
the mistake survives careful people.**

The `changed` count deserves one further note, because it fails in *both*
directions on the same node. A variable matching the default gives `changed=0`
while possibly never taking effect — under-reporting. A Gitea runner-registration
token mint always succeeds and invalidates every prior token for its scope, so it
gives `changed=1` on every run while destroying the state the running runner
depends on — over-reporting. Neither is visible without asking the runtime what
it actually holds.

## Generalisation

Applies to any verification-by-consequence, which is the strongest form of
evidence available and therefore the one most worth protecting from a bad
instrument. It is the same family as [[lesson-416]] — a guard asserting on an
input rather than the derived value — and as `#1565`, where an expectation
compared against an empty set matched everything. Here the empty set is a probe
that cannot vary.

The tell: **a check that passes and that you cannot say what it would have looked
like had the system been broken.**

## Related

- [[lesson-417-an-unapplied-iac-module-is-read-as-a-control]] — the declaration
  that reads as a control; this is its verification-side twin.
- [[lesson-413-a-credential-can-exist-authenticate-and-not-work]] — verify by
  consequence, and this lesson is what that rule needs to be safe.
- `#1538` / `#1541` — SEC-005; why 9000 is salient and why it is inert.
- `#1557` / `#1574` / `#1584` — SEC-006; the probe, the sentinel, and the guard.
- `#1565` — a guard comparing an empty set.
