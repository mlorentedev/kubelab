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

### R2 — does the image's OpenSSH honour a key registered through Gitea's API? **YES.** ✓ 2026-09-02
### R3 — does removing it fail closed, immediately? **YES, within 1 second.** ✓ 2026-09-02

Both answered by one run of `bash specs/ANSIBLE-037-dev-node-gitea-access/r2_r3_key_lifecycle_probe.sh`. The probe registers a throwaway ed25519 key on the bot account, exercises git transport with it, revokes it and retries — with an EXIT trap so a mid-probe failure cannot leave a live credential behind.

```
=== R2/R3 key lifecycle probe — 2026-09-02T03:56:04Z ===
api:    https://gitea.kubelab.live/api/v1
target: beelink.kubelab.internal:2222

token: read from prod SOPS (40 chars, value not printed)

--- [1/5] the token authenticates, and as whom ---
  File "<string>", line 7
    print(f"login={d.get(\"login\")}  ...
SyntaxError: unexpected character after line continuation character

--- [2/5] baseline: git transport BEFORE registering the key ---
git@beelink.kubelab.internal: Permission denied (publickey).

--- [3/5] register the public half via POST /user/keys (R2) ---
registered key id=2  title=ansible-037-r2-probe-20260902T035604Z

--- [4/5] git transport WITH the registered key (R2 verdict) ---
Hi there, hefesto! You've successfully authenticated with the key named ansible-037-r2-probe-20260902T035604Z, but Gitea does not provide shell access.
If this is unexpected, please log in with password and setup Gitea under another user.

--- [5/5] revoke, then retry immediately (R3 verdict) ---
DELETE /user/keys/2 -> 204
git@beelink.kubelab.internal: Permission denied (publickey).
(retry ran 1s after the DELETE; revoked id was 2)
```

**R2's verdict, and a bonus it settles.** `POST /user/keys` is sufficient: the official image's OpenSSH honours the key immediately, with no provisioning step in between. The greeting also names the account — `Hi there, hefesto!` — so **D1's identity claim is confirmed live rather than inferred from configuration**: what authenticates over this transport is the machine identity, which is what the role will provision.

**R3's verdict: fail-closed, and no cache to wait out.** The retry ran **1 second** after a `204` from `DELETE /user/keys/2` and was refused. So AC4's test asserts the revocation directly and does not need an explicit wait — a question worth asking, because a cached `authorized_keys` would have made the natural test race the cache and pass intermittently.

**The `[1/5]` SyntaxError is left in the transcript rather than cleaned up.** It is a shell-quoting bug of mine (escaped quotes inside a single-quoted `python3 -c` f-string — the same class as R1's first banner check), and it cost nothing: check `[4]` names the account anyway, which is what `[1]` existed to report. The script is fixed for future runs, but **the probe was deliberately not re-run just to produce a tidier transcript** — a second write against a live prod account is not worth cosmetics, and showing the run as it actually happened is the honest record.

### Not yet settled

Nothing. R1, R2 and R3 are closed; `proposal.md`'s "Risks / open questions" holds no unresolved item blocking Part 1. R4 was a scheduling risk (both on-demand nodes powered), satisfied for these runs.

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
