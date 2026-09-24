---
id: lesson-454-a-sops-conflict-is-resolved-by-re-setting-the-key-not-by-merging-text
type: lesson
status: active
created: "2026-09-23"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, sops, git]
---

# A SOPS file conflict is resolved by re-setting the key on upstream's file, never by merging the text

**Context**: A branch set `users_manu_password_hash` in `staging.enc.yaml`. Before it
merged, #1797 rotated Grafana's break-glass password in the same file on master. The
rebase stopped on `UU infra/config/secrets/staging.enc.yaml`.

**Problem**: The two edits touch different keys, so it looks like a textual merge. It
is not one. SOPS keeps a MAC over the whole file and a `lastmodified` stamp, and both
sides changed both. Any hand-merged result fails to decrypt, or decrypts with a MAC
error. A second trap appeared during the fix: `sops -d --extract '["a"]["b"]'` prints
the raw value, not JSON, so wrapping it in `json.loads` raised. The chained
`git rebase --continue` then committed upstream's file **without** the branch's key.
The audit caught it (`STAGING 56/57`), not the rebase.

**Solution**: Take upstream's file whole (`git checkout --ours` during a rebase). Read
the branch's value from the old commit's copy, and write it back through the toolkit,
all in one process so the value never reaches stdout:

```bash
git show <branch-commit>:infra/config/secrets/staging.enc.yaml > /tmp/old.enc.yaml
# in Python: sops -d --extract '["apps"]...["key"]' /tmp/old.enc.yaml  -> raw string
#            SecretsManager().set_secret("staging", KEY, value)
```

Then prove both sides survived, by consequence: `make secrets-audit` showed
`STAGING 57/57` (the branch's key is back), and a login probe with the SOPS value
returned `200` (upstream's rotation is intact).

**Rule**: Never resolve an `*.enc.yaml` conflict by editing text. Keep one side's file
whole, re-apply the other side's *keys* with `set_secret`, and verify both halves: the
audit for presence, a real login for value. Do not chain `rebase --continue` after a
secret step: check first, because a failed extraction still leaves a file that
rebases cleanly.

**Tags**: `#sops` `#git-rebase` `#pr-1797` `#auth-004`
