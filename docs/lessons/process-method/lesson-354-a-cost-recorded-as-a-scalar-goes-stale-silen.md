---
id: lesson-354-a-cost-recorded-as-a-scalar-goes-stale-silen
type: lesson
status: active
created: "2026-08-20"
owner: manu
category: process-method
tags: [kubelab, process-method, cost, adr, documentation, aws, gcp]
---

# A cost recorded as a scalar goes stale silently; record it as a derivation

**Context**: Evaluating a move of the Argo CD hub off AWS. ADR-023 §3.1 justified
the AWS choice partly on price: *"Cost is ~$3.60/mo (no Elastic IP — VPN-only
access)."* `MEMORY.md` carried a later figure of `~$5.33/mo`. Neither had ever
been re-derived.

**Problem**: Measured against the AWS API, the hub costs **~$12.75/mo** — 3.5x
the ADR's figure:

| Line | Rate | $/mo (730 h) |
|---|---|---|
| `t4g.small` Spot, `eu-central-1a` | $0.0109/hr | 7.96 |
| Public IPv4 | $0.005/hr | 3.65 |
| EBS 12 GB gp3 | ~$0.0952/GB-mo | 1.14 |

Three inputs had moved and none of them updated the ADR: AWS **began billing
public IPv4 on 2024-02-01** (a line item that did not exist when the ADR was
written, now 29% of the bill), the instance was upsized `t4g.micro` →
`t4g.small`, and the disk grew 8 → 12 GB.

The sharpest part is the parenthetical. *"no Elastic IP"* was a **correct** cost
argument in 2026-03, when only *idle* Elastic IPs were charged. AWS later began
charging for every public IPv4 including ephemeral ones — so a true sentence
became a false one with nobody editing a word, and it still reads as reassurance.

**Solution**: ADR-063 supersedes §3.1 and records cost as a table of
`rate × quantity` with every line item named, both for the AWS baseline and the
GCP target. The same table is carried into the spec's `verification.md`.

The check that surfaced it took one API call:

```
aws ec2 describe-spot-price-history --instance-types t4g.small \
  --product-descriptions "Linux/UNIX" --region eu-central-1
aws ec2 describe-instances --query 'Reservations[].Instances[].PublicIpAddress'
```

The second one is the important one — it proves an IPv4 is attached, which is what
turns a $0.005/hr rate into a bill.

**Rule**: **Never write an infrastructure cost as a bare `~$N/mo`.** A scalar has
no inputs, so nothing prompts a reader to re-check it, and it cannot go stale
*visibly*. Write `rate × quantity` with the line items named. Then a vendor
introducing a new charge, or a resize, shows up as a row that does not match
reality instead of a sentence that still parses fine.

Corollary for the reasoning around the number: a cost argument that depends on a
vendor's *current pricing model* ("no Elastic IP", "egress is free below X") is a
dated claim. Record the date and the model it assumes, or it will keep sounding
right long after it stops being right.

**Tags**: `#cost` `#adr` `#documentation-drift` `#issue-1181`
