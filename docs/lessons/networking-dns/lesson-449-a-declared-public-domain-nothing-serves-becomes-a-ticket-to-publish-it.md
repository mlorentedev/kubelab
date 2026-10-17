---
id: lesson-449-a-declared-public-domain-nothing-serves-becomes-a-ticket-to-publish-it
type: lesson
status: active
created: "2026-09-02"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, dns, cloudflare, loki, health-check, port-forward, pr-1530]
---

# A declared public domain nothing serves becomes a ticket to publish it

**Context**: `apps.*.domain` means "the public name this service answers on";
`health_check.py` probes `https://{domain}{health_path}` from it and
`toolkit services health --env prod` reported two permanent FAILs. #1530.

**Problem**: Three declarations named something that had never been served.
`observability.loki` claimed `loki.kubelab.live` while prod deliberately
serves `loki.internal.kubelab.local`, a non-public name ACME cannot certify.
`security.crowdsec` claimed a domain with no IngressRoute in any overlay; the
bouncer reaches it in-cluster. `platform.blog` claimed a domain for a service
`common.yaml` had recorded as killed since 2026-03-15. The Loki claim had
already generated work in the wrong direction: #1406 read the FAIL as a
missing DNS record and asked to publish an internal telemetry store. A wrong
declaration does not stay cosmetic; it becomes a ticket, and a hand-kept
table in `infra/terraform/README.md` restating `services.json` had drifted
in every row and was why anyone believed a Loki record was owed.

The same PR found a third failure mode in `obs logs`: with no `--env` it
asked whichever Loki sat on `127.0.0.1:3100`. A dev Loki was bound there, so
`No logs found` came back while prod held 20 matching lines, and an hour went
into re-measuring prod before the port became the suspect. An unreachable
Loki raises, a quiet one returns `[]`, and the wrong one answers
`status: success` with `[]`, indistinguishable from quiet.

**Solution**: Delete the false claims so the one source becomes true, each
with a comment saying why, rather than teach the health check a second
source. A guard, `tests/test_declared_domains_are_served.py`, requires every
declared public domain to have a Cloudflare record in `services.json`; it is
deliberately the weaker invariant (CI runners cannot render the overlays) and
it found the six-month-old `blog` residue on its first run. The README table
was removed, not corrected. `obs logs` now port-forwards to the named env's
Loki exactly as `obs alerts` does, and the empty-window message names the
Loki it asked. Mutation-tested: reverting to the bare client turns both new
guards red with the original message. #1406 closed as "should not exist".

**Rule**: A public name in configuration is a claim that something answers on
it, and every consumer treats it as one. Guard declared names against the
record store you can read from CI, and delete claims rather than teaching
readers to ignore them. For any client with a localhost default, an empty
answer from a reachable server is not "no data" until the client says which
server it asked; route by environment and print the address in the empty
message.

**Tags**: `#dns` `#cloudflare` `#loki` `#health-check` `#wrong-target` `#pr-1530`
