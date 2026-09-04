# Identity, auth and secret material

58 lessons, newest first. Back to [all categories](../_index.md).

| # | Lesson | Date |
|---|---|---|
| 425 | [A capability probe can stop at the first authorization layer and report the whole answer](lesson-425-a-capability-probe-can-stop-at-the-first-authorization-layer.md) | 2026-09-04 |
| 421 | [A secret read from the wrong SOPS store resolves to `''`, so a presence gate on it is open forever](lesson-421-secret-written-to-one-sops-store-read-from-another.md) | 2026-09-02 |
| 415 | [To learn whether a credential *may* do something, ask it to do something already done](lesson-415-discriminate-a-refusal-by-asking-for-something-that-already-exists.md) | 2026-09-02 |
| 413 | [A credential can exist, authenticate, and still not work — and every presence check will call that success](lesson-413-a-credential-can-exist-authenticate-and-not-work.md) | 2026-09-01 |
| 403 | [`known_hosts` has two independent ways to make a host-key purge a silent no-op](lesson-403-known-hosts-has-two-ways-to-make-a-purge-a-silent-no-op.md) | 2026-08-26 |
| 398 | [A quoting bug that breaks a command announces itself; one that widens a scope does not](lesson-398-a-quoting-bug-that-widens-a-scope-does-not-announce-itself.md) | 2026-08-26 |
| 400 | [A settled question can answer "how" without asking "at what cost"](lesson-400-a-settled-question-can-answer-how-without-asking-at-what-cost.md) | 2026-08-26 |
| 379 | [Rotating a username is not rotation, it is a rename](lesson-379-rotating-a-username-is-not-rotation-it-is-a-rename.md) | 2026-08-23 |
| 376 | [A SOPS diff answers "did this key change" without decrypting anything](lesson-376-auditing-a-rotation-without-decrypting-it.md) | 2026-08-23 |
| 335 | [Refuting a finding does not vaccinate the line it was about](lesson-335-refuting-a-finding-does-not-vaccinate-the-lin.md) | 2026-08-15 |
| 307 | [A perfect evidence chain measured against a stale baseline (SEC-001)](lesson-307-a-perfect-evidence-chain-measured-against-a-s.md) | 2026-08-09 |
| 292 | [A `sops` subprocess with a bare `os.environ` passes in your shell and returns empty in CI (TOOL-017)](lesson-292-a-sops-subprocess-with-a-bare-os-environ-pass.md) | 2026-07-08 |
| 010 | [SOPS matches `.sops.yaml` path_regex against the basename on Windows](lesson-010-sops-matches-sops-yaml-path-regex-against-the.md) | 2026-06-20 |
| 011 | [Keep SOPS ciphertext out of gitleaks, and YAML/Markdown out of CRLF, on Windows](lesson-011-keep-sops-ciphertext-out-of-gitleaks-and-yaml.md) | 2026-06-20 |
| 280 | [`notify-smoke` false-positive: `requests` follows the Authelia 303 to a 200 login page](lesson-280-notify-smoke-false-positive-requests-follows-.md) | 2026-06-17 |
| 278 | [Apprise `/status` 417 → CrashLoop: stateful mode write-tests `/config`, so the SOPS config can't be a read-only mount](lesson-278-apprise-status-417-crashloop-stateful-mode-wr.md) | 2026-06-16 |
| 277 | [n8n v2 blocks `$env` in expressions by default — use a native Header Auth credential for webhook secrets](lesson-277-n8n-v2-blocks-env-in-expressions-by-default-u.md) | 2026-06-14 |
| 274 | [Codex adversarial PR review caught 4 real defects across the OIDC sprint — bias toward verification over self-trust](lesson-274-codex-adversarial-pr-review-caught-4-real-def.md) | 2026-05-30 |
| 273 | [OIDC secret has two consumer shapes — verify per delivery mechanism, not uniformly](lesson-273-oidc-secret-has-two-consumer-shapes-verify-pe.md) | 2026-05-30 |
| 021 | [OIDC `token_endpoint_auth_method` must be declared explicitly on every client](lesson-021-oidc-token-endpoint-auth-method-must-be-decla.md) | 2026-05-26 |
| 022 | [Silent-success anti-pattern in regex-based mutation tooling](lesson-022-silent-success-anti-pattern-in-regex-based-mu.md) | 2026-05-26 |
| 020 | [Comment-vs-implementation drift — pair "auto-filled" comments with executable tests](lesson-020-comment-vs-implementation-drift-pair-auto-fil.md) | 2026-05-26 |
| 265 | [Don't put SOPS master key in CI provider secrets — use self-hosted-runner-local key](lesson-265-don-t-put-sops-master-key-in-ci-provider-secr.md) | 2026-05-23 |
| 231 | [2026-03-28: Cloudflare API token consolidated — old "DNS mlorente.dev" revoked](lesson-231-2026-03-28-cloudflare-api-token-consolidated-.md) | 2026-05-01 |
| 217 | [SEC-004: SOPS Multi-Recipient for CI (ADR-027 Phase 2, 2026-03-27)](lesson-217-sec-004-sops-multi-recipient-for-ci-adr-027-p.md) | 2026-05-01 |
| 223 | [Hub singleton credentials must always write to common SOPS](lesson-223-hub-singleton-credentials-must-always-write-t.md) | 2026-03-27 |
| 219 | [Authelia Secret changes require pod restart — RELIAB-002 only covers ConfigMaps](lesson-219-authelia-secret-changes-require-pod-restart-r.md) | 2026-03-27 |
| 222 | [Argo CD native OIDC without dex — pattern and gotchas](lesson-222-argo-cd-native-oidc-without-dex-pattern-and-g.md) | 2026-03-27 |
| 224 | [Always persist API keys to SOPS immediately after generation](lesson-224-always-persist-api-keys-to-sops-immediately-a.md) | 2026-03-27 |
| 225 | [External service credential reconciliation pattern](lesson-225-external-service-credential-reconciliation-pa.md) | 2026-03-27 |
| 191 | [Authelia access_control networks must include Tailscale CIDR](lesson-191-authelia-access-control-networks-must-include.md) | 2026-03-25 |
| 188 | [IMMUTABLE_SECRETS must be enforced in code, not just documented](lesson-188-immutable-secrets-must-be-enforced-in-code-no.md) | 2026-03-25 |
| 197 | [Authelia catch-all rules don't cover new services automatically](lesson-197-authelia-catch-all-rules-don-t-cover-new-serv.md) | 2026-03-23 |
| 203 | [Authelia restart invalidates all browser sessions](lesson-203-authelia-restart-invalidates-all-browser-sess.md) | 2026-03-23 |
| 186 | [SOPS 3.11 removed --editor flag](lesson-186-sops-3-11-removed-editor-flag.md) | 2026-03-23 |
| 165 | [enableServiceLinks: false required for n8n (same as Authelia)](lesson-165-enableservicelinks-false-required-for-n8n-sam.md) | 2026-03-22 |
| 163 | [Prod SOPS secrets must be manually synchronized with staging](lesson-163-prod-sops-secrets-must-be-manually-synchroniz.md) | 2026-03-22 |
| 156 | [Authelia ForwardAuth must filter Authorization headers](lesson-156-authelia-forwardauth-must-filter-authorizatio.md) | 2026-03-22 |
| 160 | [configure_oidc.py must use update-oauth (not delete + add-oauth)](lesson-160-configure-oidc-py-must-use-update-oauth-not-d.md) | 2026-03-22 |
| 161 | [Authelia OIDC issuer URL is request-dependent](lesson-161-authelia-oidc-issuer-url-is-request-dependent.md) | 2026-03-22 |
| 166 | [Authelia ForwardAuth must filter Authorization headers](lesson-166-authelia-forwardauth-must-filter-authorizatio.md) | 2026-03-22 |
| 153 | [OIDC first login requires account linking](lesson-153-oidc-first-login-requires-account-linking.md) | 2026-03-21 |
| 143 | [Gitea admin auto-creation via postStart lifecycle hook](lesson-143-gitea-admin-auto-creation-via-poststart-lifec.md) | 2026-03-21 |
| 148 | [Grafana OIDC is fully declarative via env vars](lesson-148-grafana-oidc-is-fully-declarative-via-env-var.md) | 2026-03-21 |
| 151 | [Gitea OIDC: CLI writes to DB but web process caches in memory](lesson-151-gitea-oidc-cli-writes-to-db-but-web-process-c.md) | 2026-03-21 |
| 139 | [OIDC client_secret flow: Authelia stores hash, client stores plaintext](lesson-139-oidc-client-secret-flow-authelia-stores-hash-.md) | 2026-03-21 |
| 145 | [OIDC hashes in ConfigMaps are NOT secrets](lesson-145-oidc-hashes-in-configmaps-are-not-secrets.md) | 2026-03-21 |
| 126 | [K8s secrets: bootstrap vs application lifecycle](lesson-126-k8s-secrets-bootstrap-vs-application-lifecycl.md) | 2026-03-17 |
| 092 | [OIDC Client Secret: Authelia Config vs Service Config](lesson-092-oidc-client-secret-authelia-config-vs-service.md) | 2026-03-01 |
| 093 | [N8N Community Edition Has No Native OIDC](lesson-093-n8n-community-edition-has-no-native-oidc.md) | 2026-03-01 |
| 099 | [Unified Secrets CLI Replaces Scattered sops/openssl Commands](lesson-099-unified-secrets-cli-replaces-scattered-sops-o.md) | 2026-03-01 |
| 095 | [sops --set Quoting: Special Characters Break JSON Parsing](lesson-095-sops-set-quoting-special-characters-break-jso.md) | 2026-03-01 |
| 096 | [Authelia OIDC JWKS: `_FILE` Env Vars Don't Work for Array-Indexed Keys](lesson-096-authelia-oidc-jwks-file-env-vars-don-t-work-f.md) | 2026-03-01 |
| 084 | [E2E Audit: CORS Wildcard Origin + Credentials Is Invalid](lesson-084-e2e-audit-cors-wildcard-origin-credentials-is.md) | 2026-02-28 |
| 085 | [Authelia Prod VPN Network Uses /24 Instead of /10](lesson-085-authelia-prod-vpn-network-uses-24-instead-of-.md) | 2026-02-28 |
| 072 | [Double Auth Anti-Pattern: Own-Auth Services Behind Authelia](lesson-072-double-auth-anti-pattern-own-auth-services-be.md) | 2026-02-25 |
| 071 | [SOPS path_regex Blocks Encrypting Files Outside Defined Paths](lesson-071-sops-path-regex-blocks-encrypting-files-outsi.md) | 2026-02-25 |
| 065 | [Authelia on K8s: Service Links Inject Conflicting Env Vars](lesson-065-authelia-on-k8s-service-links-inject-conflict.md) | 2026-02-24 |
