# The toolkit CLI, Make, Python and local tooling

49 lessons, newest first. Back to [all categories](../_index.md).

| # | Lesson | Date |
|---|---|---|
| 545 | [A fake that answers nothing cannot test what the code prints of the answer](lesson-545-a-fake-that-answers-nothing-cannot-test-what-the-code-prints-of-the-answer.md) | 2026-10-10 |
| 544 | [Gitea's `empty` flag is written at push time and never re-read from git](lesson-544-giteas-empty-flag-is-written-at-push-time-and-never-re-read-from-git.md) | 2026-10-09 |
| 541 | [A reconciler that tests presence reads an unfilled migration as converged](lesson-541-a-reconciler-that-tests-presence-reads-an-unfilled-migration-as-converged.md) | 2026-10-08 |
| 537 | [Keeping both sides of a conflict also keeps both copies of a line that must exist once](lesson-537-keeping-both-sides-of-a-conflict-also-keeps-both-copies-of-a-line-that-must-exist-once.md) | 2026-10-07 |
| 536 | [A platform.json conflict is never resolved by taking a side](lesson-536-a-platform-json-conflict-is-never-resolved-by-taking-a-side.md) | 2026-10-07 |
| 528 | [A setting that shares a name across two systems does not share its meaning](lesson-528-a-setting-that-shares-a-name-across-two-systems-does-not-share-its-meaning.md) | 2026-10-07 |
| 518 | [Poetry caches a release's file list forever, so a lock taken during the upload misses wheels for good](lesson-518-poetry-caches-a-release-file-list-taken-mid-upload-forever.md) | 2026-10-03 |
| 514 | [Poetry asks the desktop keyring even when no private source exists, and a locked keyring hangs the install with no output](lesson-514-poetry-asks-the-desktop-keyring-even-with-no-private-source.md) | 2026-10-01 |
| 504 | [A settings object built at import makes every command a secrets read](lesson-504-a-settings-object-built-at-import-makes-every-command-a-secrets-read.md) | 2026-10-01 |
| 502 | [A patch applied after import cannot see what the import already did](lesson-502-a-patch-applied-after-import-cannot-see-what-the-import-did.md) | 2026-10-01 |
| 469 | [A default argument binds at import, so monkeypatching the module constant misses it](lesson-469-a-default-argument-binds-at-import-so-monkeypatch-misses-it.md) | 2026-09-27 |
| 435 | [A stub's canned answer decides which of your assertions can fail](lesson-435-a-stubs-canned-answer-decides-which-assertions-can-fail.md) | 2026-09-05 |
| 450 | [A key appended by ruamel renders below the next block's comment](lesson-450-a-key-appended-by-ruamel-renders-below-the-next-blocks-comment.md) | 2026-09-04 |
| 432 | [A file that contains its own explanation cannot be edited by a pattern that matches it](lesson-432-a-guard-that-cannot-tell-a-warning-from-an-instance.md) | 2026-09-04 |
| 424 | [A convergence step scoped to the creation diff never repairs what already exists](lesson-424-a-convergence-step-scoped-to-the-creation-diff-repairs-nothing.md) | 2026-09-04 |
| 423 | [A fake cannot verify a request — it can only agree with whoever wrote it](lesson-423-a-fake-cannot-verify-a-request-only-agree-with-it.md) | 2026-09-03 |
| 420 | [A `try` that spans a `yield` catches the caller's failures and reports them as its own](lesson-420-a-try-around-a-yield-catches-the-callers-failures.md) | 2026-09-02 |
| 448 | [A rebuild recipe is not an inventory of what is running](lesson-448-a-rebuild-recipe-is-not-an-inventory-of-what-is-running.md) | 2026-08-25 |
| 389 | [A declaration with no readers pays its whole cost at once](lesson-389-a-declaration-with-no-readers-pays-its-whole-cost-at-once.md) | 2026-08-24 |
| 380 | [The catalog names every consumer and nothing acts on it](lesson-380-the-catalog-names-every-consumer-and-nothing-acts-on-it.md) | 2026-08-23 |
| 378 | [When two commands reach the same value, the guard on one is not a guard](lesson-378-two-paths-to-one-value-and-only-one-guarded.md) | 2026-08-23 |
| 364 | [`make` has no unknown-variable error, so a flag one target ignores is a real run](lesson-364-make-has-no-unknown-variable-error-so-an-unsupported-flag-is-a-real-run.md) | 2026-08-21 |
| 363 | [A test helper that mangles its input makes every guard downstream report on the mangled copy](lesson-363-a-test-helper-that-mangles-its-input-reports-on-the-mangled-copy.md) | 2026-08-21 |
| 352 | [A gap in an allow-list has no self-evident meaning — the same absence was the control in one list and the bug in the next](lesson-352-a-gap-in-an-allow-list-has-no-self-evident-meaning.md) | 2026-08-19 |
| 322 | [A cleanup step that reverts more than the step wrote is a destructive op wearing a check's clothing](lesson-322-a-cleanup-step-that-reverts-more-than-the-ste.md) | 2026-08-12 |
| 320 | [A domain rename is invisible to `grep` when the reference lives in a template string inside a Python generator](lesson-320-a-domain-rename-is-invisible-to-grep-when-the.md) | 2026-08-12 |
| 312 | [`.yamllint`'s own header claimed CI coverage it doesn't have](lesson-312-yamllint-s-own-header-claimed-ci-coverage-it-.md) | 2026-08-11 |
| 302 | [The same linter behind two gates in different environments is two linters — and only the lenient one was running (CI-GATE-005/006)](lesson-302-the-same-linter-behind-two-gates-in-different.md) | 2026-08-09 |
| 294 | [A deploy step that warns and exits 0 is a silent failure — the exit code is the only thing the next step reads (TOOL-021)](lesson-294-a-deploy-step-that-warns-and-exits-0-is-a-sil.md) | 2026-07-09 |
| 289 | [Windows CRLF/encoding bugs come in matched read+write pairs, and pytest's own capture can hide the bug you're testing for (TOOL-020)](lesson-289-windows-crlf-encoding-bugs-come-in-matched-re.md) | 2026-07-08 |
| 284 | [Non-ASCII glyphs (-> em-dash) in Typer/Rich CLI help/log strings crash `--help` on the Windows cp1252 console](lesson-284-non-ascii-glyphs-em-dash-in-typer-rich-cli-he.md) | 2026-06-22 |
| 283 | [`make fetch-kubeconfig` from a non-admin Windows box fails silently from PowerShell — ssh-agent in Git Bash is mandatory](lesson-283-make-fetch-kubeconfig-from-a-non-admin-window.md) | 2026-06-22 |
| 012 | [A broken language-toolchain launcher silently un-wires the dev setup](lesson-012-a-broken-language-toolchain-launcher-silently.md) | 2026-06-20 |
| 014 | [A generated artifact's content must not depend on whether secrets are decrypted](lesson-014-a-generated-artifact-s-content-must-not-depen.md) | 2026-06-15 |
| 268 | [Always `git pull` master before `make apply-secrets ENV=prod` — toolkit code runs from local checkout](lesson-268-always-git-pull-master-before-make-apply-secr.md) | 2026-05-23 |
| 025 | [Auth-boundary E2E pattern: positive + sentinel-negative + leak-grep triple](lesson-025-auth-boundary-e2e-pattern-positive-sentinel-n.md) | 2026-05-23 |
| 023 | [Fail-closed fixtures in security E2E suites](lesson-023-fail-closed-fixtures-in-security-e2e-suites.md) | 2026-05-23 |
| 079 | [2026-02-27 — Terraform: One-Time Setup vs Day-to-Day Automation Are Different Problems](lesson-079-2026-02-27-terraform-one-time-setup-vs-day-to.md) | 2026-05-01 |
| 215 | [NET-002: K8s Generator Overwrites Manual kustomization.yaml — Prod Outage](lesson-215-net-002-k8s-generator-overwrites-manual-kusto.md) | 2026-03-27 |
| 027 | [show_secret must bypass ConfigurationManager for env='common'](lesson-027-show-secret-must-bypass-configurationmanager-.md) | 2026-03-22 |
| 144 | [deploy-k8s must include apply-secrets as prerequisite](lesson-144-deploy-k8s-must-include-apply-secrets-as-prer.md) | 2026-03-21 |
| 028 | [Toolkit kubeconfig path must be env-parameterized](lesson-028-toolkit-kubeconfig-path-must-be-env-parameter.md) | 2026-03-19 |
| 116 | [Toolkit command.run must stream output for Ansible](lesson-116-toolkit-command-run-must-stream-output-for-an.md) | 2026-03-15 |
| 103 | [yamllint Directives Don't Work Inside YAML Literal Block Scalars](lesson-103-yamllint-directives-don-t-work-inside-yaml-li.md) | 2026-03-01 |
| 083 | [E2E Audit: API /health Endpoint Is Fully Mocked](lesson-083-e2e-audit-api-health-endpoint-is-fully-mocked.md) | 2026-02-28 |
| 068 | [Dev TLS cert generator missed custom root domains](lesson-068-dev-tls-cert-generator-missed-custom-root-dom.md) | 2026-02-25 |
| 067 | [Toolkit K8s Deploy Misses configMapGenerator Binary Resources](lesson-067-toolkit-k8s-deploy-misses-configmapgenerator-.md) | 2026-02-24 |
| 052 | [YAML Duplicate Keys Silently Overwrite](lesson-052-yaml-duplicate-keys-silently-overwrite.md) | 2026-02-14 |
| 044 | [ConfigurationManager vs Direct File References](lesson-044-configurationmanager-vs-direct-file-reference.md) | 2026-02-05 |
