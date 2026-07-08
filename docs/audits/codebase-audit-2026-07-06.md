# KubeLab codebase audit — 2026-07-06

Adversarial, whole-repo audit. Author read the toolkit config/secrets engine, the
Makefile/CI entry points, `common.yaml` (the declared SSOT), the K8s secret &
middleware plumbing, and the onboarding docs directly, then cross-checked every
checkable claim against the code. Findings are traced to `file:line` and marked
CONFIRMED (I followed the path end to end) or PLAUSIBLE (strong signal, one link
unverified). Where a thing is sound I say so once and move on.

> **Method note / caveat.** The intended approach was a parallel fan-out of
> per-area subagents; both waves died on a session token limit before producing
> output, so this is a single-context sequential audit. Coverage is deep on the
> **toolkit config/secret core, Makefile, CI routing, `common.yaml`, K8s
> secret/middleware modules, and onboarding docs** — the highest-blast-radius
> surfaces. It is **shallow** on: the ~124 Ansible role files, the full Kustomize
> base/overlay tree, Terraform, the 62 Docker-Compose stack files, the pytest
> suites, and `apps/api` Go source. Those areas are called out in Open Questions
> and warrant a follow-up pass. Absence of findings there is *not* evidence of
> soundness.

---

## 1. Summary

| ID | Sev | Area | Issue | Where | Status |
|----|-----|------|-------|-------|--------|
| C1 | High | secrets/DX | `age_key_env()` bypassed on the SOPS-decrypt path used by `secrets show` → `make deploy-argocd` installs Argo CD with **empty** admin-hash + OIDC secret on a fresh shell, failure masked by `\| tail -1` | `secrets_manager.py:732`, `Makefile:413-416` | CONFIRMED |
| C2 | High | secrets/correctness | Partial secret apply: a transient SOPS miss makes `kubectl apply` **replace** a live Secret with fewer keys; run still reports success | `k8s_secrets.py:294-336` | CONFIRMED |
| C3 | High | docs/DX | Onboarding Quick Start says `make dev`; **no such target exists** — the newcomer's first command fails | `README.md:123`, `apps/README.md:20` | CONFIRMED |
| C4 | High | docs/incoherence | README swaps ace2 ↔ Beelink roles (says Beelink=Ollama, ace2=MinIO+Runner) — the reverse of the SSOT; misleads ops during an incident | `README.md:31,171-172` | CONFIRMED |
| C5 | Med | boundary-safety | Secret values (incl. multi-line RSA JWKS key) passed as `kubectl --from-literal=` argv → visible in the host process table | `k8s_secrets.py:288-292` | CONFIRMED |
| C6 | Med | missing | `audit()` counts any non-empty string as "present" — a literal `REPLACE_WITH_SOPS_VALUE` placeholder passes; nothing guards against deploying it | `secrets_manager.py:509-513` | CONFIRMED |
| C7 | Med | incoherence | `SECRET_CATALOG` `grafana.admin_user` is dead — the K8s mapping uses `BASIC_AUTH_USER`; two sources for one fact, cataloged one never applied | `secrets_manager.py:216-222` vs `k8s_secrets.py:48` | CONFIRMED |
| C8 | Med | docs | README + apps/README link `apps/web/` and put it in the tree; **`apps/web` does not exist** (built in a separate repo, image received via `web-image-receiver.yml`); the real `apps/wiki` is omitted | `README.md:78,91-92`, `apps/README.md:8` | CONFIRMED |
| C9 | Med | docs | README describes prod as "Docker Compose (migrating to K3s Phase 2)"; prod is a live Argo CD **K3s** spoke with a prod overlay | `README.md:45,134` vs `common.yaml:320-321` | CONFIRMED |
| C10 | Med | correctness | Same `age_key_env()` bypass breaks `make secrets-show` / `secrets set` / `unset` on a fresh shell where the key sits only at the repo-convention path | `secrets_manager.py:732,764,793`; `configuration.py:341` | CONFIRMED |
| C11 | Low | dead-code | Wiki plumbing survives (`WikiGenerator`, `WIKI*` path constants, `config generate` default includes `wiki`) though `apps/wiki` is empty and CLAUDE.md says wiki was removed | `constants.py:126-127`, `generator_wiki.py`, `cli/config.py:66-83` | CONFIRMED |
| C12 | Low | correctness | `set_secret` wraps the value as `f'"{value}"'` for `sops set`; a value containing `"` or `\` corrupts the JSON write | `secrets_manager.py:765` | CONFIRMED |
| C13 | Low | boundary-safety | `_build_users_database` / `_build_apprise_config` hand-render YAML via f-strings; a displayname/value with `"`, `:`, or newline corrupts the Authelia users Secret | `k8s_secrets.py:255-259,216-221` | CONFIRMED |
| C14 | Low | DX | `make dev-full-reset` blocks on an interactive `@read` mid-target (hangs in any non-TTY/CI) after already running `credentials-generate` | `Makefile:290-300` | CONFIRMED |
| C15 | Low | incoherence | `COMPONENTS.SERVICES_MISC` lists calcom/immich/nextcloud, but only `.gitkeep` placeholders exist — aspirational registry entries | `constants.py:69` | CONFIRMED |
| C16 | Low | docs | `_deploy-argocd-helm` comment still says "t4g.micro OOM mitigation"; hub is t4g.small now, and the step scales **all** Argo CD to 0 on every deploy | `Makefile:406-408` vs `common.yaml:77` | CONFIRMED |

Counts: **High 4 · Medium 5 · Low 7** (16 total, all CONFIRMED).

---

## 2. System map

**Entry points.** `Makefile` is a thin orchestrator over one Python CLI
(`poetry run toolkit`, Typer app in `toolkit/main.py`) plus direct `kubectl`,
`helm`, `terraform`, and `ansible` calls. Three deploy planes:

- **Config/secret generation & K8s** — `toolkit` (`toolkit/features/*`,
  `toolkit/scripts/*`).
- **Node provisioning** — Ansible (`infra/ansible/`), inventory generated from
  `common.yaml` by `generator_ansible.py`.
- **GitOps** — Argo CD hub on AWS (`aws1`) syncing two spokes (`ace1` staging,
  `vps` prod) from `infra/k8s/argocd/applications/*`.

**The config pipeline (the spine of the whole system).**
`ConfigurationManager.get_merged_config()` (`configuration.py:100`) merges, in
override order: `common.yaml` → `{env}.yaml` → `common.enc.yaml` (SOPS) →
`{env}.enc.yaml` (SOPS), then `_inject_contact_email_derivations()` fills
operator-contact fields (SSOT-014c). `get_env_vars()` flattens the nested dict to
`UPPERCASE_UNDERSCORE` env vars (`_flatten_dict`, `:72`). Every generator
(`generator_k8s`, `generator_ansible`, `generator_traefik`, `generator_authelia`,
`generator_terraform`) consumes this same flattened view. **`common.yaml` is the
declared single source of truth for addresses, ports, images, and service
metadata** — the repo rule is "never hardcode IPs/CIDRs elsewhere."

**Secret flow.** SOPS-encrypted YAML in `infra/config/secrets/*.enc.yaml` →
`ConfigurationManager._decrypt_sops` (uses `age_key_env()` to locate the age key)
→ two consumers: (a) `k8s_secrets.apply_secrets` builds K8s `Secret`s via
`kubectl create secret generic --from-literal … --dry-run=client -o yaml | kubectl
apply`; (b) `k8s_middlewares.apply_middleware_secrets` renders Traefik `Middleware`
CRDs that embed an API key and server-side-applies them. `secrets_manager.py`
holds the `SECRET_CATALOG` (authoritative registry) and audit/init/rotate/hash
operations.

**Key invariants and where they live (or don't):**
- *Secrets never land in ConfigMaps* — enforced by a **denylist**
  (`VALIDATION_RULES.SECRET_PATTERNS`) substring-matched in
  `generator_k8s._extract_app_env_vars` (`:307-311`). Fragile by construction
  (CLAUDE.md admits it; the beehiiv `pub_id` leak is the documented precedent).
- *Secret exists ⇒ mount it* — enforced structurally by tying the mount to
  `SECRET_DEFINITIONS` (`generator_k8s._has_secret_vars`, `:316`). Sound.
- *age key is discoverable without shell setup* — enforced by `core/sops.py`
  `age_key_env()`, but **only on the paths that call it** (see C1/C10).
- *Value files match reality* — **not enforced anywhere**: no schema validation,
  no unknown-key warning, no cross-registry consistency check (see Design
  Tensions).

**External surfaces:** the `toolkit` CLI (11 sub-apps), `make` targets,
`*.enc.yaml` SOPS files, `~/.kube/kubelab-{env}-config`, Cloudflare API
(Terraform), GitHub (Actions + `gh`), and the Traefik-fronted HTTP surface of
every service in `common.yaml`.

---

## 3. Findings by category

### Correctness & silent failure

**C1 — `secrets show` bypasses `age_key_env()`; `make deploy-argocd` silently
installs Argo CD with blank secrets.** CONFIRMED.
`SecretsManager.show_secret` (`secrets_manager.py:732`) runs `subprocess.run(["sops",
"-d", …])` with **no `env=` argument** — it inherits `os.environ` unchanged. The
whole reason `core/sops.py` exists (see its module docstring) is that this repo's
age key lives at `~/.config/age/key.txt`, *not* a SOPS-default path, so without
`SOPS_AGE_KEY_FILE` exported, `sops -d` fails with "failed to get the data key."
`_decrypt_sops` avoids this by passing `env=age_key_env()`; `show_secret` does not.
Now follow `Makefile:413-416`: `deploy-argocd` extracts the Argo CD admin hash,
OIDC client secret, Slack webhook, and GH webhook secret via
`toolkit secrets show … | tail -1` and feeds them straight into `helm upgrade
--set`. On a fresh shell (new clone, cron, the agent harness, a CI box that didn't
export the var) each `show` fails, `| tail -1` swallows the error, and the value
is **empty** → Argo CD is installed with a blank admin password hash and blank
OIDC client secret. Scenario: operator on a machine where the key is only at the
repo path runs `make deploy-argocd` → hub comes up unauthenticatable / SSO broken,
with no error surfaced. Direction: route `show_secret`/`set_secret`/`unset_secret`
through `env=age_key_env()` like the rest of the module; separately, make the
Makefile fail loudly if any extracted secret is empty (`test -n`).

**C2 — Partial secret apply replaces a live Secret with fewer keys.** CONFIRMED.
`_apply_single_secret` (`k8s_secrets.py:283-298`) collects `--from-literal` args
for the keys it can resolve; if *some* are missing but *at least one* resolves, it
logs a warning and proceeds (`:294-298`). It then does `kubectl create secret …
--dry-run=client -o yaml | kubectl apply -f -`, which **replaces** the entire
Secret. So if a single source value is transiently absent (an env-specific SOPS
key not yet synced — CLAUDE.md admits staging/prod aren't auto-synced), the live
`api-secrets` (or any multi-key Secret) is overwritten with a subset, silently
dropping the previously-present keys. `all_ok` stays `True` because the `apply`
itself succeeds. Scenario: `infra.smtp.pass` present but `zoho_client_secret`
missing in prod → `make apply-secrets ENV=prod` shrinks `api-secrets` to 3 keys;
the API pod loses `ZOHO_CLIENT_SECRET` on next restart. Direction: treat a
resolved-key count below the mapping's expected count as a failure (or use
`kubectl patch`/merge semantics), and never report success on a partial mapping.

**C10 — `age_key_env()` bypass also breaks `secrets-show`/`set`/`unset` and
`batch_update_secrets`' decrypt step.** CONFIRMED. Same root cause as C1 on a
wider surface: `secrets_manager.py:764` (`set_secret`) and `:793` (`unset_secret`)
call `sops` with no `env=`; and `configuration.py:341` — the decrypt step *inside*
`batch_update_secrets` — passes `env=os.environ` even though the sibling
`_decrypt_sops`/`_encrypt_sops_file` in the same class use `age_key_env()`.
Scenario: on a fresh shell (key only at `~/.config/age/key.txt`), `make
secrets-show KEY=…` returns nothing, and `secrets init`/`credentials generate`
fail to decrypt an *existing* populated vault (the empty-file fast path works,
masking it until the vault has content). Direction: one helper (`age_key_env()`)
on every `sops` subprocess in the codebase; add a regression test asserting no
`sops` call is made with bare `os.environ`.

**C12 — `set_secret` corrupts values containing `"` or `\`.** CONFIRMED.
`secrets_manager.py:765` builds `["sops", "set", file, path, f'"{value}"']`. The
last arg must be valid JSON; wrapping the raw value in quotes breaks the moment
`value` contains a double-quote or backslash (e.g. a generated password or an
external token). No shell is involved (list argv) so it's not injection, but the
write silently produces malformed JSON or a wrong value. Direction: `json.dumps(
value)` instead of manual quoting.

### Boundary & safety

**C5 — Secret material (incl. the RSA JWKS private key) is exposed in the process
table.** CONFIRMED. `k8s_secrets.py:288` appends
`f"--from-literal={k8s_key}={value}"` for every secret key, including
`oidc_jwks_key` (a multi-line RSA-4096 PEM) and every password/token, then passes
them as `kubectl create secret` **argv**. On the operator machine, any local
process can read these via `/proc/<pid>/cmdline` (`ps auxww`) for the lifetime of
the call. On a single-user workstation the blast radius is small, but it's a real
plaintext-in-argv exposure and it undercuts the care taken elsewhere (the
middleware module goes out of its way to avoid annotation leaks). Direction: feed
values via stdin (`kubectl create secret … --from-file=/dev/stdin` per key, or
build the Secret YAML in-process and `apply -f -`) rather than argv.

**C13 — Hand-rolled YAML for the Authelia users DB and Apprise config is
injection-fragile.** CONFIRMED. `_build_users_database` (`k8s_secrets.py:255-259`)
emits `displayname: "{displayname}"`, `email: {email}`, `password: "{hash}"` via
f-strings with no escaping; `_build_apprise_config` (`:216-221`) does the same for
telegram URLs. A user `displayname` containing a `"` (or a stray `:`/newline
anywhere) produces an invalid `users_database.yml`, and the resulting Secret makes
Authelia fail to parse its user DB — locking everyone out. Values are
maintainer-controlled today so it's low-likelihood, but it's the wrong layer to
trust raw strings. Direction: build a dict and `yaml.safe_dump` it.

### Missing functionality

**C6 — `audit()` cannot tell a real secret from a placeholder.** CONFIRMED.
`secrets_manager.py:510` marks a key `present` iff `str(value).strip()` is
non-empty. The repo's own K8s `secrets.yaml` ships `REPLACE_WITH_SOPS_VALUE`
placeholders by design; nothing in audit/init/apply rejects that literal, so a
half-configured vault reports clean, and a placeholder can reach a cluster. `make
secrets-audit` — the documented drift-detector — would show it as satisfied.
Direction: treat a known placeholder set (and perhaps suspiciously short/`CHANGE_ME`
values) as *missing* in `audit()`.

### Incoherence & duplicated truth

**C7 — `grafana.admin_user` is a dead catalog entry; the applied username comes
from `basic_auth.user`.** CONFIRMED. `SECRET_CATALOG` registers
`apps.services.observability.grafana.admin_user` (`secrets_manager.py:216-222`) as
a first-class secret, but the K8s mapping wires Grafana's `admin-user` to
`BASIC_AUTH_USER` (`k8s_secrets.py:48`) — as does Gitea's `ADMIN_USER` (`:70`). So
the cataloged Grafana username is never applied, and three services' admin
identity is silently pinned to one `basic_auth.user` value. Two sources for one
fact that can drift, plus a catalog entry that lies about being used. Direction:
delete the dead catalog entry or make the mapping consume it; document the shared
`basic_auth.user`→admin coupling explicitly.

**C11 — Dead wiki subsystem.** CONFIRMED. `apps/wiki/` has no tracked files, and
CLAUDE.md states wiki was "removed — integrated in toolkit as `kubelab docs`."
Yet `WikiGenerator` (`generator_wiki.py`), the `WIKI`/`WIKI_DOCS` path constants
(`constants.py:126-127`), and the `config generate` default service list
(`cli/config.py:66,69` include `"wiki"`) all still reference it. `toolkit config
generate` with no `--service` will attempt wiki generation against an empty dir.
Direction: remove the generator, constants, and CLI wiring; or restore the source
if `kubelab docs` still needs it.

**C15 — `SERVICES_MISC` lists services that don't exist.** CONFIRMED.
`constants.py:69` enumerates `calcom`, `immich`, `nextcloud`, but the repo has only
`infra/stacks/services/misc/{calcom,immich}/.gitkeep` and no manifests/compose.
These are aspirational entries in a registry that's meant to describe reality.
Direction: drop them until they're real, or mark the tuple as "planned."

### Documentation drift

**C3 — `make dev` (documented onboarding command) does not exist.** CONFIRMED.
`README.md:123` ("Start development stack: `make dev`") and `apps/README.md:20`
both instruct `make dev`. The Makefile has `up-dev`, `down-dev`, `restart-dev`,
`build-dev`, `dev-full-reset`, `dev-full-clean` — **no bare `dev` target**. A
newcomer's literal first command after `make setup` fails with `No rule to make
target 'dev'`. This is the single worst first impression in the repo. Direction:
add a `dev` alias (`dev: up-dev`) or fix both docs to `make up-dev`.

**C4 — README swaps ace2 and Beelink node roles.** CONFIRMED. `README.md:31`
("ace2: GH Runner + MinIO", "Beelink: Ollama") and the Hardware Topology block
`:171-172` ("Acemagic-2 — Platform node (GH Runner + MinIO)", "Beelink — Ollama")
are the **exact reverse** of the SSOT: `common.yaml:118` marks ace2 `# ADR-028:
Ollama only`, `:163` marks Beelink `# ADR-028: MinIO + GH Runner + Glances`, and
`infra/k8s/base/external/ollama.yaml:16,41` points the Ollama EndpointSlice at
`100.64.0.5` = ace2. CLAUDE.md's gotchas say the same. Scenario: Ollama is down at
3am; the on-call reads the README, powers on Beelink, and chases the wrong box.
Direction: swap the two in both README locations.

**C8 — README references a nonexistent `apps/web/`; omits `apps/wiki/`.**
CONFIRMED. `README.md:78` links `[Web](apps/web/)` and `:91-92` puts `web/` in the
tree; `apps/README.md:8` does the same. `apps/` actually contains only `api/`,
`wiki/` (empty), and `README.md`. The `web` app is built in a **separate repo** and
its image is received here via `web-image-receiver.yml` (`repository_dispatch:
web-image-published`), which is why `ci.yml`'s change-detection filters only `api`
and `errors` (`:63-64`) — contradicting `README.md:140` ("only builds affected
apps (api, web, errors)"). Direction: drop the `apps/web` link, note web is
external, and either populate or remove `apps/wiki`.

**C9 — README says prod is Docker Compose "migrating to K3s Phase 2"; prod is a
live K3s spoke.** CONFIRMED (the drift; one operational link — whether the Compose
stack is fully retired — left to the maintainer). `README.md:45,134` frame prod as
Docker-Compose-with-K3s-pending. But `common.yaml:320-321` registers prod as an
Argo CD spoke on `vps`, `_deploy-authelia-oidc` (`Makefile:396-400`) `kubectl apply
-k infra/k8s/overlays/prod` against `kubelab-prod-config`, a full prod overlay
exists, and `register-spoke ENV=prod` is a supported flow. Direction: update the
README prod description to K3s.

**C16 — Stale Argo CD deploy comment + full scale-to-zero each deploy.**
CONFIRMED. `Makefile:406` labels the pre-upgrade scale-down "t4g.micro OOM
mitigation", but `common.yaml:77` shows the hub is now `t4g.small` (the
`ebs_size_gb: 12` note at `:83` and ADR-033 confirm the upgrade). The step scales
**all** Argo CD deploys+statefulsets to 0 on every `deploy-argocd` (`:407-408`) —
a real availability dip on each run; documented as a safety net but worth
revisiting now that RAM headroom exists. Direction: refresh the comment; gate the
full scale-down behind a flag.

### Developer experience

**C14 — `make dev-full-reset` hangs on interactive input mid-target.** CONFIRMED.
`Makefile:290-300`: after `dev-full-clean` + `credentials-generate` (which already
mutates state), the target prints manual instructions and blocks on `@read -p ""`
until the user hits Enter. In any non-TTY context (CI, a wrapped invocation, the
agent harness) this hangs forever, and it's already done destructive work by then.
Direction: split the interactive step out, or detect non-TTY and abort early with
guidance.

---

## 4. Design tensions

1. **A hand-rolled config engine with no schema and many parallel registries.**
   The system's spine is `dict → flatten → UPPERCASE env vars → Jinja/kubectl`.
   There is no schema validation of the value files, no unknown-key warning, and
   no cross-registry consistency check — yet "adding one service" touches at least
   six places that must agree by hand: `common.yaml`, `COMPONENTS`
   (`constants.py`), `SECRET_CATALOG`, `SECRET_DEFINITIONS` (`k8s_secrets.py`),
   `MIDDLEWARE_CATALOG`, and a `.tpl`. C7 (dead `grafana.admin_user`), C11 (dead
   wiki), and C15 (phantom misc services) are the *observable symptoms* of
   registries drifting from reality with nothing to catch it. Alternative to
   weigh: a single typed model (pydantic/dataclass schema) that the value files
   are validated against at load time, with the component/secret registries
   *derived* from it rather than maintained in parallel. That converts a class of
   silent drift into a load-time error.

2. **Secret handling mixes a careful path and a careless one.** `k8s_middlewares.py`
   is exemplary — server-side apply to avoid annotation leaks, gitignored audit
   copies, `age_key_env()` throughout. `k8s_secrets.py` and the `secrets_manager`
   show/set path are the opposite — argv-exposed values (C5), f-string YAML (C13),
   partial replace (C2), and `age_key_env()` bypass (C1/C10). The same rigor
   applied in one module needs to be the module-wide standard. Alternative:
   funnel *all* Secret creation through one primitive that (a) always uses
   `age_key_env()`, (b) never puts secrets in argv, (c) builds YAML via a
   serializer, and (d) fails closed on any missing key.

3. **The denylist keeping secrets out of ConfigMaps is inverted risk.**
   `SECRET_PATTERNS` (`constants.py:191`) is a substring allow-through-unless-matched
   filter. Its failure mode is silent *leakage* (the documented beehiiv `pub_id`
   incident), and every new secret-ish field is a chance to miss the pattern. A
   denylist that fails open on the secret path is the wrong polarity. Alternative:
   an explicit allowlist of ConfigMap-eligible keys (or: everything under a SOPS
   file is secret by origin, full stop — never pattern-matched), so a
   misclassification fails toward *exclusion*.

4. **README is a second, drifting SSOT for topology and onboarding.** C3, C4, C8,
   C9 all trace to the README asserting facts (node roles, app layout, prod
   substrate, first command) that the code and CLAUDE.md already own and that have
   since changed. For a solo-maintained platform the README is precisely what a
   future-you or a collaborator reads first, and it's the least-tested artifact in
   the repo. Alternative: generate the topology/app tables from `common.yaml`
   (the `dashboard`/`networking` blocks already hold node metadata), so the
   human-facing doc can't diverge from the SSOT.

---

## 5. Expectation gaps (expected X, found Y)

- Expected `make dev` (documented in two READMEs) → **no such target**; onboarding
  breaks on the first command. (C3)
- Expected README hardware topology to match the SSOT → **ace2/Beelink roles
  reversed**. (C4)
- Expected `apps/web/` (linked, in the tree) → **absent**; web lives in another
  repo. (C8)
- Expected `secrets show` / `deploy-argocd` to decrypt on a fresh shell (the
  literal promise of `core/sops.py`) → they **bypass `age_key_env()`** and return
  empty, silently. (C1/C10)
- Expected `apply-secrets` to be all-or-nothing → it **applies partial Secrets**
  and reports success. (C2)
- Expected `secrets-audit` to catch an unconfigured vault → a **placeholder passes
  as present**. (C6)
- Expected `SECRET_CATALOG` to be *the* authoritative registry → at least one
  entry (`grafana.admin_user`) is **never applied**. (C7)

## 6. Open questions (need the maintainer / can't resolve from code alone)

1. **Is `apps/web` intentionally external?** `web-image-receiver.yml` strongly
   implies web is built in its own repo and only its image lands here. If so the
   README links are just wrong (C8); if not, the source is missing. Confirm the
   intended home of `apps/web`.
2. **Is the prod Docker-Compose stack fully retired?** The Argo CD prod spoke +
   overlay are live (C9), but CLAUDE.md still has VPS Docker-Compose gotchas and a
   `deploy-vps` guard that skips Traefik/errors "when K3s is active." Is prod
   currently K3s-only, or a hybrid mid-cutover?
3. **`homepage-secrets` wiring.** `k8s_secrets.py:100-105` sources
   `APPS_SERVICES_DASHBOARD_HOMEPAGE_*`, but `common.yaml` has no
   `apps.services.dashboard` namespace and `generator_k8s._find_var` has no
   `DASHBOARD` search path. Does Homepage get these from SOPS under that path, or
   is the mapping orphaned? (Could not confirm without decrypting.)
4. **Uncovered areas (from the Method caveat).** The Ansible role tree, full
   Kustomize base/overlays, Terraform, the Compose stacks, the pytest suites, and
   `apps/api` Go source were not audited in depth. A second pass — ideally the
   originally-intended parallel fan-out, once token budget allows — should target
   idempotency/`no_log` in Ansible, `kustomize build` correctness for both
   overlays, and whether the e2e/infra tests read addresses from `common.yaml` as
   the repo rule requires.

---

*Findings are uncommitted; the maintainer owns git. A fixing agent should cite the
stable IDs (C1…C16). Highest leverage: C1+C10 (one `age_key_env()` fix closes a
silent deploy-time footgun) and C3+C4+C8+C9 (a single README pass fixes the
onboarding cliff).*
