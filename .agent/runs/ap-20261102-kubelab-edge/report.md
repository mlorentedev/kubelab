# Run report: ap-20261102-kubelab-edge

**Verdict: done, with one item parked and one disclosure.** Queue worked to the end; 5 of 6 items closed.

## Waiting on you

- #2977: choose (A) a `preStop` sleep for `web` in the generator, or (B) accept the loss. Options are on the ticket.

## Disclosure

`make provision NODE=vps ENV=prod TAGS=k3s` did more than the `k3s_server` role the envelope authorized. The tag also applied roles already merged on master: `node_notify` (7 changes, including a new spool timer) and `node_maintenance` (1). The run read them only afterwards. No regression seen. `make setup-ansible` also moved this Mac's `community.general` to the pinned 13.5.0, because the provision refused the stale copy.

## Items

| Item | Result |
|---|---|
| #2995, OPS-054 | Merged, spec archived (#3013) |
| #3000 | Closed (#3009) |
| #2975, OBS-043 | Merged (#3019), applied to staging and prod |
| #2977, DELIVERY-012 | Parked, Blocked on the board: the fix is outside `write_paths` |
| #2993, #2986 | Closed |

## Parked

#2977: at 50/s, a `web` rollout lost 0.34% of 14,975 requests with a 5,001 ms maximum; `api` lost 0 of 15,001. One run each.

## Unmerged

None from this run. Filed: #3010, #3012, #3018.

## Evidence

- Prod Traefik: `limits.memory 1536Mi`, new pod, 0 restarts at about 3 minutes.
- Prod routes after: apex 301, grafana 302, auth 200, vpn 200, the same as before.
- `make alerts`: none firing or pending, about 6 minutes after the change.
- Staging, 1,536Mi: no OOMKill in 8 ramps, highest sample 973 MiB. Only one step reached 3,200 VUs.
- Traefik still restarted at 1,600/s, from its liveness probe (#3018).

## Budget

About 5h50m of 6h. Six items. No failure breaker tripped.

## Host

`caffeinate` was armed for 6h15m, so the whole window was covered.

## Next action

Decide #2977.
