# Runbook — rotating a secret after it has been exposed

> Use this when a secret's **value** has left SOPS: pasted into a chat or terminal transcript,
> printed by a command, committed by accident, or sent to a third party. Routine scheduled
> rotation is a different task — see each secret's `rotate_note` in `SECRET_CATALOG`
> (`toolkit/features/secrets_manager.py`), which is the SSOT for how any individual secret is
> re-issued.

## The rule that matters

**Revoke at the provider first, update SOPS second.** Not the other way round.

Updating SOPS first leaves the old value valid at the provider for as long as it takes you to get
to the revocation step, and the exposed copy is exactly the one an attacker already has. Revoking
first makes the leaked value worthless immediately; the brief outage between revoke and update is
the price, and it is much cheaper than the alternative.

For the same reason, do not treat "the secret is only in a private transcript" as safe. Transcripts
get synced, backed up, and pasted into issues. Treat exposure as public.

## What NOT to do

- **Do not run `make credentials-generate`.** It regenerates *machine* credentials — OIDC client
  secrets, HMAC, session secret, Grafana/Gitea admin passwords. External provider tokens are not
  in its scope, so it will not fix the leak, and it will churn a pile of unrelated secrets that
  then need redeploying.
- **Do not print secret values to check your work.** The safe pattern is to print key *paths* only:

  ```bash
  sops -d infra/config/secrets/common.enc.yaml | python3 -c '
  import sys, yaml
  def walk(n, p=""):
      if isinstance(n, dict):
          for k, v in n.items():
              cur = f"{p}.{k}" if p else k
              print(cur) if not isinstance(v, (dict, list)) else walk(v, cur)
  walk(yaml.safe_load(sys.stdin))'
  ```

  A `grep -A3` over `sops -d` output prints values, not names. That is a real observed cause of
  exposure here, not a hypothetical one.

## Procedure

1. **Enumerate exactly what leaked.** Key paths, not guesses — a rotation that misses one leaves
   the incident open, and one that includes extras causes needless redeploys. Use the paths-only
   snippet above.
2. **Revoke at the provider.** Per-provider notes below.
3. **Issue the replacement** at the provider.
4. **Write it into SOPS** — never with an editor, always through the toolkit:
   ```bash
   toolkit secrets set <key.path> --env common     # or --env staging|prod
   ```
   Note `secrets set` takes `--env common` to select the *file*; this is the opposite meaning of
   `SecretSpec.envs`, which is an audit dimension. See the CLAUDE.md gotcha.
5. **Redeploy the consumers.** Look up the secret's `rotate_note` in `SECRET_CATALOG` — it names
   them. A rotated secret sitting in SOPS while services still hold the old value in memory is a
   half-done rotation that looks finished.
6. **Verify**: `make secrets-audit` shows no gap, and the consuming service actually works. An
   audit is presence-only (#686) — it cannot tell a valid token from a revoked one, so exercise
   the path.
7. **Record it**: note the date and the key paths in the incident's ticket or session record.

## Provider notes

| Provider | Revoke at | Notes |
|---|---|---|
| Cloudflare API token | dash.cloudflare.com → My Profile → API Tokens | Roll rather than delete if you want zero DNS downtime: create the new token, update SOPS, redeploy, then delete the old one. Scope the replacement to the same permissions — a broader token is its own incident. |
| Cloudflare Tunnel token | dash.cloudflare.com → Zero Trust → Networks → Tunnels | Rotating the token requires reconfiguring the connector; the tunnel is down until it reconnects. |
| GitHub PAT | github.com → Settings → Developer settings → Personal access tokens | Revocation is immediate. Check the token's scopes before reissuing — reissue the narrowest set that still works. |
| Uptime Kuma API key | Uptime Kuma UI → Settings → API Keys | Revoke and reissue; the consuming dashboard needs the new value redeployed. |

## Recording the instance

The procedure lives here; **a specific incident does not.** This repository is public, so naming
which credentials leaked and when would advertise exactly what to hunt for and narrow the search
for anyone who cared — the rotation closes the hole, but the record would keep pointing at it.

Record each occurrence in the private knowledge store instead: the date, the exact key paths, the
consumers redeployed, and — importantly — which nearby keys were checked and confirmed **not**
exposed, so a later reader does not rotate them out of caution. Precision matters in both
directions: missing one leaves the incident open, and including extras causes needless redeploys.
