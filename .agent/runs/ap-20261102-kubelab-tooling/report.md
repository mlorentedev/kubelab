# Run report: ap-20261102-kubelab-tooling

Armed 2026-11-02T05:55Z, expires 2026-11-02T17:50Z. Reason: queue-empty. Nothing was widened.

## Landed

| Item | PR |
|---|---|
| #2847 Makefile raw FROM/TO | #2960 |
| #2873 pull budget transfer-only | #2962 |
| #2870 notify spool follow-ups | #2969 |
| #2866 clockless notices | #2996 |
| #2896 edge shape cap check | #2979 |
| #2755 retire Kuma hand stack | #2985 |
| #2712 headscale setup runbook | #2988 |
| #2945 resolver literals, Corefile half | #2980 (ticket stays open) |

## Parked, each with options on the ticket

- #2540: needs root `poetry.toml`, outside write_paths, and a window with no sessions running.
- #2945: the Headscale list is 1.1.1.1/1.0.0.1 and differs from `public_resolvers`; owner chooses.

## Filed from work

- #2986 DOCS-031 headscale-setup leftovers.
- #2994 ANSIBLE-089 provision RPi 3 from bare OS.

## Caveats

- Reviews were PR-Agent only for most of the run: Codex and CodeRabbit hit limits. Each triage comment says so.
- The advisor was rate-limited, so no second opinion ran.
- Nothing was deployed. The node_notify changes reach nodes at their next provision.
- Local notify tests ran under a `flock` stand-in on macOS; 5 lock-contention tests fail there and pass in CI.
