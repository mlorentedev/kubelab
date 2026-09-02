---
tags: [spec, verification, templates]
created: "2026-09-01"
---

# Verification - ANSIBLE-037-dev-node-gitea-access

## Open questions, settled

A settled question with no transcript is an assertion. Each entry below carries the command that produced it.

### R1 — is Gitea's SSH transport usable from ace2? **YES.** ✓ 2026-09-02

`bash specs/ANSIBLE-037-dev-node-gitea-access/r1_transport_probe.sh`, run from the workstation against ace2 over the tailnet, with both on-demand nodes powered:

```
=== R1 transport probe — 2026-09-02T03:52:15Z ===
from:   ace2
target: beelink.kubelab.internal:2222

--- [1/3] TCP reachability from ace2 ---
OPEN — something is listening
(exit 0)

--- [2/3] SSH banner (which server answers) ---
debug1: Remote protocol version 2.0, remote software version OpenSSH_10.0

--- [3/3] git transport as the machine identity ---
git@beelink.kubelab.internal: Permission denied (publickey).
```

**Verdict: SSH is usable, so `proposal.md` D2 stands as written** — a per-node key registered on `hefesto`'s account, blast radius on ace2 limited to repositories. The HTTPS fallback is not taken, so no re-recording of D2 is needed.

**Why `Permission denied (publickey)` is the positive result, not a failure.** The question R1 asks is whether a server is *there and working*, not whether this session already has access. All three checks agree that it is: the port accepts a TCP connection, the server identifies itself as **OpenSSH_10.0** (the official image's OpenSSH on container port 22, exactly what the compose template says publishes there), and it completed a host-key exchange — the first run of this probe added the `[beelink.kubelab.internal]:2222` ED25519 host key to ace2's `known_hosts`. It then refused authentication for the one reason the role exists to fix: no public key has been registered. A dead port answers with a connection refusal or a timeout; it does not negotiate and then reject you by name.

**This is the specific failure the probe existed to rule out.** The compose template records that the K8s manifest it replaced "set `SSH_LISTEN_PORT=2222` without enabling that server, so nothing was listening on the port it published — one of the reasons its advertised clone URL had never connected." That is a published port with nothing behind it, and it is indistinguishable from a working one by reading configuration. Check 1 alone would not separate the two either, since Docker publishes the port regardless; only checks 2 and 3, which require a server to actually answer, do.

**One correction made mid-probe, recorded rather than quietly fixed.** Check 2's first implementation read the banner by hand (`exec 3<>/dev/tcp/...; head -c 120 <&3`) through two levels of shell quoting, and returned empty — not "no banner", but no output at all. It was rewritten to read `ssh -v`'s own `remote software version` line. A diagnostic that silently returns empty is worse than no diagnostic: it looks like a measured negative.

### R2, R3 — not yet run

`hefesto` key acceptance and revocation semantics. Both need a key registered against the bot account, which is the first task of Part 1.

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

-
-

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons/`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/ANSIBLE-037-dev-node-gitea-access/` -> `specs/archive/ANSIBLE-037-dev-node-gitea-access/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
