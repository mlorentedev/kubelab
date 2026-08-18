---
id: lesson-268-always-git-pull-master-before-make-apply-secr
type: lesson
status: active
created: "2026-05-23"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# Always `git pull` master before `make apply-secrets ENV=prod` — toolkit code runs from local checkout

**Context:** SSOT-012 PR #3 (#210) merge → validation flow. Ran `make apply-secrets ENV=prod` immediately after PR merge. The local master had not been re-pulled since the merge; an earlier `git pull` (pre-merge) returned "Already up to date" so I assumed local was current. It wasn't.
**Problem:** The toolkit (`toolkit/features/k8s_secrets.py`) runs from the local checkout's Python — whatever code is in the working tree IS the source of truth for the apply. Local master was at `6a4ef78` (pre-#210); origin/master had advanced to `094af52`. The apply used the OLD `SECRET_MAPPING` (still mapping `EMAIL_PASS` + `EMAIL_USER`), producing a K8s Secret with the OLD keys. The pods that just restarted to pick up the NEW ConfigMap (which has `INFRA_SMTP_*`) would have been crash-looping looking for `INFRA_SMTP_PASS` that wasn't in the Secret. Caught by `kubectl get secret api-secrets -o jsonpath='{.data}'` showing old keys, NOT by `make apply-secrets`'s success message (which only reports kubectl apply success, not "the keys I just applied match the latest master").
**Solution:** Three rules going forward: (1) Always `git pull` master before `make apply-secrets ENV=prod` — even if you just pulled. Especially after a merge to master, the auto-merge may have happened seconds after your last pull. (2) After `make apply-secrets`, verify the Secret keys with `kubectl get secret <name> -n kubelab -o jsonpath='{.data}' | python3 -c "import json,sys; print(sorted(json.load(sys.stdin).keys()))"`. The toolkit's success message only tells you kubectl didn't error, NOT that the apply matched the latest catalog. (3) Consider extending the toolkit `apply-secrets` to print `[INFO] toolkit at SHA <X> (master at <Y>) → applying N secrets` so the version mismatch is visible without manual verify. Captured during validation of SSOT-012 PR #3 — would have caused a prod outage if I'd done apply→restart without the explicit key verification step.
**Tags:** `#secrets` `#gitops` `#process` `#patterns`
