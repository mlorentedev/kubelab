---
spec: "SEC-032-oidc-key-from-sops"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "58977709e5074b4b1d01c1d7e8badb8baaac1d1f"
reviewer: "nan/deepseek-v4-flash"
date: "2026-10-14"
---

## Adversarial review

**Scope**: SEC-032-oidc-key-from-sops (`git diff 65c08339598982f6dd6a5516081e259cea45c468...HEAD`, 2 commits, 16 files, +318/-48)
**Sources**: `specs/SEC-032-oidc-key-from-sops/{proposal,tasks,verification}.md`, `features.json`; diff over `toolkit/`, `infra/stacks/services/security/authelia/compose.base.yml`, `docs/`, `tests/test_oidc_signing_key_single_store.py`

### Spec and task alignment

All five acceptance criteria are met, and I reproduced the two that carry risk rather than reading the author's assertions:

- **AC1 (mechanism)** — reproduced end-to-end, not just asserted. `docker compose -f compose.base.yml -f compose.dev.yml run --rm --no-deps authelia authelia validate-config` returned **rc 0, "Configuration parsed and loaded successfully without errors."** with no host pem on disk and with the environment the toolkit itself builds (`DockerService._get_execution_env("dev")`). The template's `secret "/config/secrets/oidc-jwks.pem"` therefore resolves inside the container from the Compose secret. Separately verified that the toolkit exports exactly the name the compose file consumes: `APPS_SERVICES_SECURITY_AUTHELIA_OIDC_JWKS_PRIVATE_KEY` present, 3243 chars, PEM-shaped (value never printed). The pytest-level link is the derived `ENV_NAME = SECRET_CATALOG key_path.upper().replace(".", "_")`, which agrees with `ConfigurationManager._flatten_dict` (joins with `_`, uppercases) — so the test binds the compose variable to the SOPS key path, not merely to a string that happens to match.
- **AC2/AC3 (single store)** — `generate_jwks` no longer writes, `credentials.py` step 8 is gone, `JWKS_FILE_TEMPLATE` and the dead template variable are gone. Repo-wide grep finds no host-pem read or write in `toolkit/` or `infra/`; the only remaining `oidc-jwks.pem` under `infra/` is the in-container path (compose `target`, the `.j2` template, the gitignored generated dev config).
- **AC4 (live)** — reproduced the loadable-config half (rc 0 above, no host pem). The *stricter* half of the author's claim — the container's public-key fingerprint equals SOPS's — I did **not** re-derive; treat the fingerprint equality as author-reported, independently consistent with rc 0 (an empty or malformed key fails this check).
- **AC5 (docs)** — reproduced: `bash scripts/check-lessons.sh` → `check-lessons: OK (564 lessons)`, rc 0; both runbooks name SOPS as the only store.
- **Tests pass** — reproduced independently: `make test-fast` → **4587 passed, 18 skipped, 176 deselected, 2 xfailed**, matching `verification.md` exactly. The 12 related suites (`secrets`, `docker_service`, `authelia`, `oidc`) → 116 passed.
- **Mutation checks** (the tests are not decorative): renaming the compose env var (`..._KEY_TYPO`) turns `test_the_key_is_a_secret_sourced_from_the_sops_variable` **red**; reintroducing a host pem path + `JWKS_FILE_TEMPLATE` into `toolkit/*.py` turns `test_nothing_reads_or_writes_a_host_copy` **red**. Both reverted; tree clean.
- **Risk probes that came out clean** (each was a candidate Blocker, killed with evidence): with the env var unset Compose fails **loudly** (`environment variable "…" required by secret "…" is not set`, rc 1) rather than materialising an empty key — no silent-broken-signing path. `validate_volume_mounts`/`_missing_bind_sources` only inspects `services.*.volumes`, so the new top-level secret cannot be misread as a missing bind source and block `up`. A rotated value **does** reach the container on the next `docker compose up` (probe: KEYA → KEYB), so rotation is not swallowed by a cached copy — that dev-only "second store after rotation" is not a defect.
- **No tests deleted** (diffstat has no test deletions); no `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags in any spec file.
- **UNVERIFIED**: `make validate-sync` (claimed in `verification.md`) — not run in this window; the change removes an unused template variable, so a generated-output diff is unlikely but unproven by me.
- `proposal.md` frontmatter still reads `status: draft` with all five ACs ticked — a **Question**, not a requested edit: the contract set is frozen by this verdict, and the archive checklist owns the status transition.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | regression guard | The AC3 guard's reach is narrower than the claim it enforces ("nothing in `toolkit/` or `infra/` … A guard test fails if one reappears"). `_text_files()` scans `Makefile` plus `toolkit/**` and `infra/**` restricted to suffixes `.py .yml .yaml .j2 .sh .mk`; anything else — `.toml`, `.json`, `.tpl`, `Dockerfile`, `.md`, `.gitignore`, or `scripts/`, `docs/`, other root files — is invisible, as is any filename that does not literally contain `oidc-jwks.pem` (underscore variant, bare `.pem`, or a path assembled from parts). It also detects *naming*, not *minting*: a re-added `generate_jwks_rsa_key()` call that writes nothing would pass, though the observed drift mechanism was always a write. | This session: identical offending content in `toolkit/_probe_guard_tmp.py` → guard **red** (1 failed); in `toolkit/_probe_guard_tmp.toml` → **4 passed** (blind). No such file exists today, so the gap is latent, not live. | UNTESTED (no test asserts the guard's own coverage set) | tests |
| Minor | REAL | knowledge hygiene | `docs/adr/adr-016-oidc-centralized-auth.md:71` states the private key is `apps.services.security.authelia.oidc_jwks_rsa_private_key` — that path exists nowhere in the repo; the real key is `…authelia.oidc_jwks_private_key`. AC5 corrected the two runbooks but left the ADR naming a store that does not exist. | `grep -rn oidc_jwks_rsa_private_key` → only that ADR line | UNTESTED (docs) | docs (repo, outside the contract set) |
| Minor | REAL | test hermeticity | The guard scans gitignored generated output (`infra/config/authelia/generated/**/*.yml`, gitignored per `Makefile:279`), so what it inspects depends on whether `toolkit config generate` has run locally — the same check can scan different file sets on two machines. | `_text_files()` globs `infra/**` for `.yml`; `generated/` is gitignored | UNTESTED | tests |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All five ACs met and the key path reproduced end-to-end; the uncovered negative path is the guard's reach, not the happy path. |
| Verification       | B | Evidence is reproducible and I reproduced the suite, `validate-config` and the lesson check; `make validate-sync` and the AC4 fingerprint equality remain author-reported. |
| Scope              | A | Diff matches the proposal one-for-one; no creep, no test deletions, no unrelated files. |
| Reliability        | B | Loud failure when the variable is absent, rotation propagates on the next `up`, no cached copy — the guard's blind spot and the fresh-env dependency on `toolkit secrets jwks` keep it off A. |
| Maintainability    | B | Small functions, comments explain WHY (the SEC-032 note in `credentials.py` is the right shape); the guard's scope is undocumented relative to the claim it states. |
| Handoff-readiness  | B | Lesson-568, two runbooks, `features.json` and `verification.md` are all in place; the PR/triage closing box in `tasks.md` is legitimately still open at review time. |

### Verdict
PASS WITH GAPS

One open Major, and it is **THEORETICAL** (latent: no such file exists today, and the realistic regression site — a writer in `toolkit/*.py` — is covered, proven by mutation). Two REAL Minors. No Blocker, no REAL Major, no D or C dimension — so the reality rule holds the change at PASS WITH GAPS rather than FAIL, and the gaps are tracked, not fixed.

### Recommended next steps

Every item below is outside the contract set (`proposal.md`, `tasks.md`, `features.json`), which is closed by this verdict — do **not** edit those three; any edit invalidates this review and its archive permission.

- **Guard reach (Major, first)** — widen `_text_files()` to an explicit, asserted coverage set (suffixes plus roots), and add a case that a reintroduced host path in a non-scanned file fails. Fix is test-only and can ride a follow-up PR; scope it as a ticket if it does not fit the current one.
- **ADR-016 (Minor)** — correct `oidc_jwks_rsa_private_key` → `oidc_jwks_private_key` in `docs/adr/adr-016-oidc-centralized-auth.md:71`.
- **Hermeticity (Minor)** — exclude gitignored generated output from the guard, or make its inclusion explicit; fold into the guard fix.
- **Disposition record** — record these three in `verification.md` (applied / ticketed / declined with a reason); it is excluded from the staleness check for exactly this purpose.
- **Close the handoff** — open the PR with a `## Knowledge` section and triage it (`## Review triage`), which is the one open `tasks.md` closing box.
- **Archive** — `dotf spec archive SEC-032-oidc-key-from-sops` is **advisable** once the PR is up and triaged: this review is fresh for the current contract digests (`review-request.json`: features.json `182573d1…`, proposal.md `586c750a…`, tasks.md `5864b2c6…`) and carries no Blocker. If the guard fix lands as part of this change rather than a follow-up, re-run the review instead.
