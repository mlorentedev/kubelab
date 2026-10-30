---
id: lesson-678-a-retry-inside-one-request-cannot-outlive-an-outage-of-its-path
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: observability
tags: [kubelab, observability, notify, systemd]
---

# A retry inside one request cannot outlive an outage of the path it takes

**Context**: `kubelab-notify@` retries its POST to n8n inside curl for about 30 seconds (ANSIBLE-038). On 2026-10-29 ace2 held six failed notifiers, four from the window in which the lab edge was down (#2787).

**Problem**: On a LAN node every name resolves through the edge, so with the edge down the request failed on DNS in its first second, and the retry budget was spent against an outage that lasted hours. The unit failed, and that failed state was the only trace: nothing sent the notice later. #2733's rule, "a page that failed to deliver is not recorded as sent", made the next failure try again. That covers a short blip but not an outage, and it pages again for a failure the operator was never told of.

**Solution**: Keep the notice on the node and count it as sent. A timer delivers the spool later (`--flush`). The kept notice carries the time it happened in its title, because n8n shows it when it arrives. Order is the part that has to be designed. A recovery sent live while its failure still waits would arrive first, and n8n's router reads a `page` that is not marked resolved as a failure, so the late failure would open an alarm for a closed incident. So a notice is sent directly only when it holds the spool's lock and the spool is empty. Otherwise it is kept behind what waits, and the flush is started. That covers a failure already kept. A failure still on the wire is covered by the unit's own lock: the recovery waits up to 40 seconds for it, longer than one delivery's worst case of 30, and a role test holds the two apart. With a shorter wait the recovery would go out first. The flush stops at the first refusal. A notice older than a week is dropped with a line in the journal, so one payload that n8n refuses for good cannot hold the rest behind it. `tests/test_node_notify_dedup.py` runs the shipped script with a shimmed curl. Twenty-one mutants go red, among them one that lets a recovery overtake its failure and one that sends while a flush holds the spool.

**Rule**: A retry budget measured in seconds covers a blip, not an outage of the path itself. If a message must survive an outage of the path it takes, store it on the sending side, and decide the order between the stored path and the live one: whatever reads the messages in sequence will see an overtaken one as a new event.

**Tags**: `#notify` `#systemd` `#spool` `#issue-2787`
