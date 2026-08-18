---
id: lesson-018-merge-dependabot-config-changes-before-closin
type: lesson
status: active
created: "2026-06-14"
owner: manu
tags: [kubelab, lesson]
---

# Merge Dependabot config changes BEFORE closing its PRs

**Context**: Added `.github/dependabot.yml` (#618) where none existed; on merge Dependabot opened a 14-PR burst of version updates. To cut churn I started closing the *grouped* PRs (#614 security group, #628 web-minor-patch group) before the follow-up calibration PR (#644 — sets `open-pull-requests-limit: 0` on departing ecosystems) was merged.

**Problem**: Closing a grouped Dependabot PR while the live config still permits that update makes Dependabot re-evaluate and recreate the group's members as **individual** PRs. Closing #614 + #628 exploded ~12 grouped updates into ~17 individual PRs (15 → 27 open), each queuing CI on the single self-hosted runner — a cleanup turned into a recreation storm. Separately, the version-update `ignore` (astro major) does **not** suppress **security** updates: astro 5.x had 3 advisories fixed only in astro 6, so astro→6 PRs reappeared regardless of the ignore.

**Solution**: Stopped closing. Cancelled the queued Dependabot CI runs (`gh run list ... | while read id; do gh run cancel "$id"; done`, filtered to `headBranch` starting `dependabot/`) to free the runner for #644. Correct order: (1) merge the config that disables the updates, (2) then close the stragglers — once `limit: 0` is live they do not recreate. For the security-driven astro PRs the lever is dismissing the Dependabot alert (accept-risk, tracked) or doing the upgrade — `ignore` won't stop them.

**Rule**: Change Dependabot's *config* first, close its *PRs* second. Never close a grouped Dependabot PR while the live config still permits that update — it ungroups into individual PRs. And remember `ignore: version-update:semver-major` does not block security updates; suppress those by dismissing the alert, not via ignore rules. Bonus (runner): a single on-demand self-hosted runner has no autoscaling/fallback headroom — a flood (or a powered-off host) blocks the whole queue. Tracked as OPS-005 (GitHub-hosted fallback); K8s HPA does not apply (runner is a Docker Compose service on Beelink, not a pod — ARC would be the K8s-native autoscaler).

**Tags**: `#dependabot` `#ci` `#gotcha` `#ordering` `#self-hosted-runner` `#pr-618` `#pr-644`
