---
tags: [spec, verification]
created: "2026-10-26"
---

# Verification - VPN-ACL-006-headscale-upgrade

## Current status

Contract frozen by the operator on 2026-10-29: the three gate-review
amendments are accepted and the WIP exception is renewed for this spec. Only
the read-only AC1 preflight is authorized for implementation; no production
operation is authorized or completed. The target v0.29.6 is a candidate, not
an installed version or frozen container digest. All feature acceptance
remains pending.

## Evidence

| Criterion | Required evidence | Current result |
|---|---|---|
| AC1 | Client/bridge compatibility and approval preflight tests | NOT IMPLEMENTED |
| AC2 | Candidate image/config/consumer checks | NOT IMPLEMENTED |
| AC3 | Required private/subnet traffic plus no unintended broadening | NOT RUN |
| AC4 | Consistent backup, synthetic migration and old-version full restore | NOT RUN |
| AC5 | Native assertions with populated state; rejected write/reload detection | NOT RUN |
| AC6 | Reconnect/identity checks and second apply `changed=0` | NOT RUN |
| AC7 | Safe-default, approval, redaction and failure-cleanup tests/runbook | NOT IMPLEMENTED |

## Test status

The authoritative prepared checkout was fast-forwarded from `2d9ca0da` to
`e1d9be29`. The separate main checkout at `dfed764e` is older; its earlier
34-test pass is not evidence for the current baseline.

Executed the existing targeted suite with the prepared checkout's Python
environment, no inherited pytest plugins, no bytecode/cache/coverage output,
and a PATH without SSH, SOPS or age:

```text
python -B -m pytest -o addopts= -p no:cacheprovider
  tests\test_headscale_role.py
  tests\test_headscale_hosts_entry_owner.py
  tests\test_headscale_probe_hub_source.py -q
2 failed, 35 passed in 11.73s
CURRENT_OFFLINE_BASELINE_EXIT=1
```

The first hosts-owner test stops on `Path.read_text()` using Windows cp1252
for a UTF-8 Ansible source (`UnicodeDecodeError`). The synthetic second-writer
test compares native backslash paths against POSIX fixture paths and fails.
No source fix, encoding override or skip was applied. This is a non-green
baseline, not an upgrade regression or proof that no other failures exist.

No Docker candidate drill, live backup, restore, client compatibility audit,
image-digest verification, deployment, policy reload or full regression suite
ran. No runtime convergence or independent review is claimed.

Documentation-only checks, all exit 0:

```text
pre-commit markdownlint: Passed
pre-commit check-json: Passed
DOC CONTRACT: YAML frontmatter, JSON, local links and whitespace PASS
TRACEABILITY: AC1-AC7 covered by tasks and pending features; no orphan AC tags
RUNTIME ACCEPTANCE: NOT RUN; feature commands refer to planned implementations
```

## Planning evidence and boundaries

- GitHub REST confirmed issue #248 open.
- Upstream release metadata lists v0.29.6 as stable, published 2026-10-24.
- v0.29.0 notes document wildcard changes, mandatory adjacent-minor upgrades,
  blocked minor downgrades, hostname/config/CLI changes and native policy tests.
- Native tests require populated database state; a plain standalone syntax
  check can warn instead of executing them.
- The operator approved a planning-only exception after the generator refused
  12 active specs against limit 10. The generated frontmatter retains that reason.
- Reused the existing external worktree; no new branch/worktree was created.
  Its inherited name is not approval for another control plane.
- Configuration improvements are limited to compatibility and safe rollout;
  permission tightening and denial-preserving segment rollback remain separate.

## Gate review, 2026-10-29

Read-only preparation after the operator asked to start. No implementation,
image change or production command ran. The operator froze the contract the
same day, accepting the amendments in `proposal.md`.

- **G1 WIP:** `dotf spec audit` on `origin/master` reports
  `[OK] 12 active spec(s), every one tracking an open issue` (no zombie spec to
  archive). Still over the limit of 10, so starting code needs either two specs
  to close or a renewed operator exception.
- **G1 coverage (pre-freeze `/spec check`):** deterministic path; every
  Implementation task carries an `[ACn]` tag, AC1-AC7 each have at least one
  covering task, no orphan tasks. Verdict PASS. Re-run after any contract edit.
- **G7:** both Windows failures are test portability defects, not product
  defects: `Path.read_text()` used cp1252 and the scan reported native
  separators. Fixed in #2820 (`read_text(encoding="utf-8")`,
  `relative_to(root).as_posix()`); the same three files then gave `37 passed`
  on Windows. #2820 merged on 2026-10-29 (`cd38905`); G7 is closed.
- **G3 image:** Docker Hub `headscale/headscale:v0.29.6` resolves to OCI index
  `sha256:cabe84f0699913dbca9320f0883dca7565dd08df3c5be29edfabbebeff763966`,
  with `linux/arm64/v8`
  `sha256:8c89809526c15c1c0ff4a49cc205e0f7d9b9fe2533f476eabdb2a95363a2f08a`
  and `linux/amd64`
  `sha256:d080ca49bf379cc8d6b8df07f0d11d7fb3d11812965a09c2c3a1acfb3c6e6130`.
  Current `v0.28.0` index is
  `sha256:51b1b9182bb6219e97374fa89af6b9320d6f87ecc739e328d5357ea4fa7a5ce3`.
  Read anonymously from the registry API on 2026-10-29; re-resolve at freeze.
- **G3 upstream v0.29.1-v0.29.6:**
  - v0.29.1 fixes nodes losing their user on upgrade, so v0.29.0 is not an
    acceptable target.
  - v0.29.2 logs nodes with invalid FQDNs at startup.
  - v0.29.3 rejects `/key` below the capability floor, so a client under
    Tailscale 1.80.0 is cut off rather than degraded (hardens G2).
  - v0.29.4 really disconnects expired nodes; a node online today with an
    expired key goes offline at upgrade.
  - v0.29.5 fixes a rejected policy leaving its packet filter active (#3501),
    which is the upstream half of AC5/#2190.
  - v0.29.6 is a security release (Go 1.27.3, CA bundle, x/net, gRPC).
- **G3 configuration:** `config.yaml.j2:70` sets the deprecated
  `ephemeral_node_inactivity_timeout` (now `node.ephemeral.inactivity_timeout`).
  It uses none of the removed keys (`randomize_client_port`, `oidc.expiry`).
  `trusted_proxies` is new and unset; prod Headscale sits behind K3s Traefik,
  so v0.29 stops honouring forwarded client addresses from it.
- **G4:** policy rule 1 grants `kubelab@`, `manu@` and `work@` `"*:*"`.
  v0.29.0 resolves `*` to `100.64.0.0/10` and `fd7a:115c:a1e0::/48` only, so
  as written the upgrade removes their access to the rpi4-advertised
  `networking.lan_cidr`. `render_headscale_policy.py` already renders that
  CIDR as host alias `lan-rpi4`, so the explicit destination needs no new
  address list.
- **G1 PR split (frozen 2026-10-29; the operator authorized 1 and 2 only):**
  each PR stays under the 300-line cap and none mutates production by
  merging alone.
  1. Spec only: this folder, on a branch whose name does not imply a second
     Headscale instance.
  2. AC1 preflight: read-only eligibility in `toolkit/features/headscale_upgrade.py`
     plus tests. It has no infrastructure effect.
  3. G4 policy: add `lan-rpi4:*` to rule 1. It is a no-op on v0.28, where `*`
     already covers it, so it can be deployed and observed ahead of the upgrade.
  4. AC4 backup, migration and restore sequencing, reusing #433 and
     `headscale_drill.py`.
  5. AC3/AC5 disposable drill and its `make headscale-upgrade-drill` target,
     reusing #2184 and #2190.
  6. AC2 + AC6/AC7: configuration keys, `trusted_proxies`, the digest pin,
     rollout guards and the runbook. Merging this changes what the next VPS
     deploy installs, so it waits for the production window approval (G8).

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? Unanswered: review at archive.
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? Unanswered:
  ADR-041 already requests the upgrade; reassess if implementation changes architecture.
- [ ] New pattern candidate for `00_meta/patterns/`? Unanswered: review at archive.

## Archive checklist

- [ ] Resolve all acceptance gates and collect receipts.
- [ ] Independent fresh review and promotion decisions recorded.
- [ ] Archive only after completion; issue #248 remains open.
