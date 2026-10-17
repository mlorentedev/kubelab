---
id: lesson-586-an-upgrade-probe-needs-the-same-run-on-the-deployed-version
type: lesson
status: active
created: "2026-10-17"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, gitea, upgrade, restore-drill, baseline]
---

# A failing check on the new version proves nothing until the old version fails it too

**Context**: OPS-038 rehearses the Gitea 1.25.5 to 1.27.3 upgrade by starting the candidate image on the newest R2 snapshot (`make backup-drill-gitea`, BACKUP-040) and probing it: `gitea doctor check --all`, the REST v1 contract `dotf forge` uses, and merge settings read back after `PATCH`.

**Problem**: The first run on 1.27.3 failed the doctor probe with "1 error line", which read as an upgrade finding. Printing the context showed the failing check was `Garbage collect LFS`. The same drill on the deployed 1.25.5, against the same snapshot, reported the same error plus two more, and both runs exited 0, so the status code said nothing either. Left unexamined, the rehearsal would have blamed the upgrade for an old defect, or been "fixed" by loosening the probe for good.

**Solution**: Run the identical probes on the deployed image first (a throwaway branch pinning 1.25.5 and `make backup-drill-gitea ENV=prod HOST=ace2`), then exclude only what fails there, by check name, with the measurement as the reason (`KNOWN_BASELINE_FAILURES` in `toolkit/features/gitea_upgrade_probe.py`). The contract and merge-settings probes passed on both versions, which is the real statement: nothing `dotf forge` calls changed. 1.27.3 reported fewer doctor errors than 1.25.5.

**Rule**: A rehearsal probe is judged by the difference between the candidate and the deployed version on the same data, never by its absolute result. Run the baseline before reading the candidate's failures, key exclusions on a named check with a measured reason, and read the exit code and the text separately, because a tool can report a failure in only one of them.

**Tags**: `#gitea` `#upgrade` `#restore-drill` `#ops-038`
