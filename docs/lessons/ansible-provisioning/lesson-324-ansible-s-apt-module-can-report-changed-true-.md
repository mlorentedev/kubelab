---
id: lesson-324-ansible-s-apt-module-can-report-changed-true-
type: lesson
status: active
created: "2026-08-14"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# Ansible's `apt` module can report `changed: true` for two unrelated reasons that both look like "nothing really happened"

**Context:** OPS-017 (#960) added `base_system` to rpi3's provisioning playbook — the first time that role had ever run on a Debian-family node (every other fleet node is Ubuntu). Getting it to a clean, idempotent, `--check`-safe state surfaced two distinct bugs in the same two tasks, on the same node, in the same session.

**Bug 1 — `--check` fails on a completely standard package.** A `CHECK=1` dry-run failed with `No package matching 'vim' is available`, even though `vim` is a stock Debian package. Root-caused by reading the vendored module source (`ansible/modules/apt.py`, around line 1415) rather than guessing: `update_cache`'s real work — `cache.update()` — is wrapped in `if not module.check_mode:`, so a `--check` run never actually refreshes the on-disk apt cache, yet the task still unconditionally reports `changed: true` for it. Confirmed independently that this node's cache really was empty (`find /var/lib/apt/lists -name '*Packages*'` → 0 files, since `base_system` — the only place `apt update_cache` is declared — had never run here before). A `--check` run therefore evaluates every subsequent `apt: name: ...` task against a cache that was never populated. Proof the diagnosis was right, not just plausible: the identical `CHECK=1` command, re-run after a real (non-check) pass had genuinely refreshed the cache, passed clean.

**Bug 2 — a real run keeps reporting `changed: true` for a package that's already installed.** After fixing Bug 1, an idempotence re-run still showed `changed: true` on "Install base packages", even though `apt-get`'s own output said `0 upgraded, 0 newly installed`. `dnsutils` is a pure virtual package on Debian trixie — `dpkg -l dnsutils` reports `un` (unknown, no entry at all), only `Provides` from the real package `bind9-dnsutils`. Ansible's `apt` module pre-checks the *literal requested name* against dpkg before invoking `apt-get`, and does not resolve `Provides` the way `apt-get` itself does — so it never finds `dnsutils` "installed" and re-invokes `apt-get install dnsutils` every run, which itself is a real no-op (apt resolves the virtual name correctly) but the module still reports it as `changed`. On Ubuntu 24.04, `dnsutils` happens to be a genuine transitional package with its own dpkg entry (`ii`), which is why this had never surfaced anywhere else in the fleet — rpi3 was the first Debian-family tester. Fixed by naming the real package (`bind9-dnsutils`) instead of the virtual alias — a no-op rename on Ubuntu, a real fix on Debian.

**Rule:**
- **A module reporting `changed: true` is a claim about what the module *decided to attempt*, not proof that a real state change occurred — verify against the underlying tool's own output (`apt-get`'s "0 upgraded, 0 newly installed") before trusting the module's own changed/unchanged signal**, especially the first time a role runs against a new OS family.
- **`--check` mode is not "the same logic, minus writes" for every module** — some modules (this `apt` one included) skip specific side-effecting calls under check-mode while still reporting the task as changed, which can make a `--check` run fail on things a real run would have fixed for itself moments earlier. When a `--check` failure looks absurd (a stock package "unavailable"), suspect the dry-run's own state assumptions before the repo's config.
- **A package's identity in Ansible's `apt` module is the literal string in `dpkg`'s database, not what `apt-get` would resolve it to.** Virtual/transitional packages are exactly where these two views diverge; when adding a fleet role to a new OS family for the first time, check every package name against that OS's `dpkg -l`, not just whether `apt-get install` would succeed.

**Tags:** `#ansible` `#apt` `#debian` `#check-mode` `#idempotence` `#ops-017` `#gotcha`

---
