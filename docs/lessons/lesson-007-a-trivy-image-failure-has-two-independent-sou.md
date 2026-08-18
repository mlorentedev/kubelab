---
id: lesson-007-a-trivy-image-failure-has-two-independent-sou
type: lesson
status: active
created: "2026-06-26"
owner: manu
tags: [kubelab, lesson]
---

# A Trivy image failure has two independent sources — base-OS *and* the Go binary

**Context**: The `api` image build (Trivy step in `ci-publish.yml`, gate = `CRITICAL,HIGH`, `ignore-unfixed: true`) started failing on the release PR. First read: the base was `alpine:3.18`, which had reached EOL — its apk packages no longer get security backports, so ~18 fixed-elsewhere HIGH/CRITICAL CVEs tripped the scanner. Bumped the runtime base to the current stable `alpine:3.24`.

**Problem**: The base bump cleared every OS CVE — and Trivy *still* failed. Trivy scans a container image with **two independent scanners**: the OS package DB (apk/apt — the alpine layer) **and** `gobinary`, which reads the dependency versions baked into the compiled Go binary. The remaining HIGHs were all the second kind: stale *transitive* Go modules (`golang.org/x/crypto` 0.40, `golang.org/x/net` 0.42, `golang.org/x/sys`, `quic-go` 0.54) — untouched by any base-image change because they live in the binary, not the rootfs. A multi-stage Dockerfile makes this easy to miss: the runtime layer looks clean, but the `COPY`d binary carries its own vuln surface. Bonus trap: bumping the deps raised the `go` directive (1.23→1.25), and the newer toolchain's `vet` then failed the build on a **pre-existing** non-constant format string (`fmt.Errorf(x)` where `x` is a runtime value) that the older vet had ignored.

**Solution**: Fixed both sources in one PR — `alpine:3.24` for the OS half, and `go get golang.org/x/crypto@latest golang.org/x/net@latest golang.org/x/sys@latest github.com/quic-go/quic-go@latest && go mod tidy` for the gobinary half (all are `// indirect`, so forcing the higher version + tidy is the patch). Then fixed the vet diagnostic the go-directive bump surfaced (`fmt.Errorf("%s", x)`).

**Rule**: When an image fails Trivy, read the finding's **package type before reaching for the base image**: an apk/deb name (`libssl3`, `ca-certificates`) is an **OS** CVE → bump/patch the base; a module path (`golang.org/x/...`, `github.com/...`) is a **gobinary** CVE → bump the Go dep (`go get @latest` + `go mod tidy`, even for `// indirect`). A green base does not mean a green image. Because the gate is `ignore-unfixed: true`, every failure is by definition *actionable* (a fix exists upstream). And expect a `go` directive bump to activate newer `vet` checks on old code — budget for a small follow-up fix. Two prevention hooks now exist: Dependabot `docker` (base EOL) + `gomod` security updates (binary deps).

**Tags**: `#trivy` `#security` `#docker` `#golang` `#gobinary` `#supply-chain` `#ci` `#sec-scan-001`
