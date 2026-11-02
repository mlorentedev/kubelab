---
id: lesson-610-a-docker-user-rule-matched-by-original-destination-also-catches-the-replies
type: lesson
status: active
created: "2026-10-21"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, iptables, uptime-kuma, incident]
---

# A DOCKER-USER rule matched by original destination also catches the replies

**Context**: #2482 restricts Uptime Kuma's published port on rpi3 to the machines
that need it: the node of each Argo CD spoke and the operator's workstation. A ufw
rule cannot do it, because Docker's DNAT runs before ufw's chains, so the role adds
a `KUMA-ALLOW` chain jumped to from `DOCKER-USER` with
`-m conntrack --ctorigdst <tailnet ip> --ctorigdstport 3001`. `--ctorigdst` was
chosen because after DNAT the packet's destination is the container, and only the
conntrack original tuple still names the published address.

**Problem**: the first apply in prod dropped everything, allowed sources included,
and `status.kubelab.live` went down for about two minutes (03:45Z to 03:47Z). The
chain's LOG rule named the cause at once: `SRC=172.20.0.2`, the Kuma container.
`DOCKER-USER` sits in FORWARD and sees both directions. A reply belongs to the same
connection, so its original destination is the same published address, and the
jump sent Kuma's replies into the allowlist with the container as source.

**Solution**: the chain's first rule returns the reply direction, so only the
client's direction is judged:

```
-A KUMA-ALLOW -m conntrack --ctdir REPLY -j RETURN
```

Re-applied through the role (`make provision NODE=rpi3 ENV=prod TAGS=allowlist`).
After that, prod and staging routes returned 200, the operator's Mac 302, and ace2
and rpi4 timed out, each one logged as a drop. A second run reported `changed=0`.

**Rule**: a conntrack match on the ORIGINAL tuple (`--ctorigdst`, `--ctorigdstport`)
selects a connection, not a direction. In FORWARD it matches the replies as well,
so a source-based allowlist behind it must exclude `--ctdir REPLY` first. Ship the
LOG rule with the DROP: it turned an outage with no visible cause into a one-line
diagnosis.

**Tags**: `#iptables` `#docker-user` `#2482`
