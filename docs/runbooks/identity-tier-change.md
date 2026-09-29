# Changing someone's access tier

> ADR-062 D2 (amended by AUTH-011). Run on AUTH-004 AC2, which took `operator`
> out of `admins`, and on AUTH-011, which gave `users` an operating tier.

## The model

A tier is a group in Authelia's users database. Each app maps it on its own:

| Group | Argo CD | Grafana | Gitea |
|---|---|---|---|
| `admins` | `role:admin` | Admin | admin |
| `users` | `role:operator` (read, sync, resource actions) | Editor | user |
| anything else | `role:readonly` | Viewer | refused (Gitea requires `users`) |

Membership is declared once, in `groups:` under
`apps.services.security.authelia.users` in `infra/config/values/common.yaml`.
What each group *grants* lives in each app: Argo CD's `policy.csv` in
`infra/helm/argocd/values.yaml`, Grafana's role path in
`infra/k8s/base/services/grafana-config/grafana.env`, Gitea's auth source flags.

## Moving an account between tiers

1. Edit its `groups:` in `common.yaml`, open a PR and merge it.
2. Land the users database. It is a Secret, so a merge does not deliver it:

   ```bash
   make apply-secrets ENV=staging   # then ENV=prod
   ```

   This restarts Authelia too. Authelia never reloads the users file on its own
   (lesson-455). Skipping this step for one env is silent: Argo CD reports
   Synced/Healthy, and Authelia keeps sending the old `groups`. If Grafana
   still shows the old role after a fresh login in that env, this step is
   what was missed: `auth-review` cannot see it yet (#1911).
3. Correct what each app already stored:

   ```bash
   make auth-review ENV=prod           # what each app holds now, against what is declared
   make auth-review ENV=prod APPLY=1   # correct it
   ```

   How quickly each app follows differs:

   | App | Where the tier lives | After `APPLY=1` |
   |---|---|---|
   | Gitea | `is_admin` in its database | Edited through the API. Takes effect at once. |
   | Grafana | Org role, written from `groups` at each OAuth login | The account's sessions are revoked. The role changes at its **next login**. |
   | Argo CD | Nothing stored. `groups` come from UserInfo | Nothing to edit. The change is seen within **1h**, the access token's lifespan (lesson-471). |

## Changing what a tier grants

- **Argo CD policy**: edit `policy.csv`, merge, then `make deploy-argocd`. A
  merge alone never reaches the hub. `test_argo_cd_rbac_lets_users_operate_and_never_administer`
  runs Argo CD's own evaluator over the shipped file in CI.
- **Grafana role path**: edit `grafana.env` and merge. Argo CD rolls Grafana.
  Every account keeps the role of its last login until it signs in again, so
  run `make auth-review ENV=<env> APPLY=1` afterwards to revoke the sessions of
  every account the change moves.

## Verifying

**By consequence, never by reading the config.** `make auth-review` reads the
live privilege over each app's break-glass path.

- **Grafana still reads the old role after `APPLY=1`.** The account has not
  signed in since. Find its last request in Loki and compare it with when the
  Grafana pod loaded the new config:

  ```bash
  poetry run toolkit obs logs -e prod -s grafana --since 24h \
    -q '{container="grafana"} |~ "uname=<login>|ROLE_ATTRIBUTE_PATH"'
  ```

  Requests older than the `ROLE_ATTRIBUTE_PATH` line were made under the old
  path. Measured on 2026-09-27: `operator` last signed in at 02:10Z, and the new
  path loaded at 03:14Z. The drift was that login, not a broken path. Ask the
  user to sign in once, then run the review again.
- **Argo CD denials.** The UI opens the confirmation dialog *before* the server
  authorizes (lesson-473). Never confirm a destructive action to prove a
  denial. Check the allowed half in the browser (a Sync). Check the denied half
  with the evaluator over the live policy, until AUTH-012 (#1876) folds it into
  `auth-review`:

  ```bash
  kubectl --kubeconfig ~/.kube/kubelab-hub-config -n argocd \
    get cm argocd-rbac-cm -o jsonpath='{.data.policy\.csv}' > policy.csv
  docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/w" -e KUBECONFIG=/w/kc \
    quay.io/argoproj/argocd:<argocd.app_version> \
    argocd admin settings rbac can users delete applications '*/*' \
    --policy-file /w/policy.csv --default-role role:readonly
  ```

  `kc` is a placeholder kubeconfig (`user: {token: none}`). The command needs
  one to start, and it never contacts the cluster. Exit 0 means allowed.
- **Break-glass accounts** are local and belong to no group. `auth-review`
  lists them (`sign-in: Auth Proxy` or `local`), and they are not moved by any
  of this. See [break-glass](break-glass.md).
