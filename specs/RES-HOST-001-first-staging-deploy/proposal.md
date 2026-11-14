---
id: RES-HOST-001-first-staging-deploy
type: proposal
status: draft
created: "2026-11-13"
issue: "mlorentedev/kubelab#2366"
owner: manu
---

# RES-HOST-001: resume's first staging deploy through the product contract

## Problem

resume (`ghcr.io/mlorentedev/resume`, forge `personal/resume`) has to run on the
cluster through the product contract (ADR-067, IDP-053), not from hand-written
manifests (owner, #2366, 2026-10-20). Contract schema v1 cannot express what
resume needs: one RWO volume shared by the web Deployment and a daily CronJob,
access restricted to the `admins` group, a pod `fsGroup`, and a hostname pair
that follows the platform-service convention. ADR-073 (proposed) designs these
as claims, but it is not accepted, and its acceptance gate (D2's sealing-key
verification) cannot ride on resume's path because resume seals nothing.

This spec carries the owner's latest decisions on #2366 (the comment dated
2026-11-14 in the issue) to the first staging deploy, and nothing past it.

## Scope (owner decisions, not reopened here)

1. `resources:` in ADR-073 D3's shape `{name: {type, class?, params}}`, with
   only `volume` and `job`. `forwardauth` narrowed to `admins`. `fs_group`.
2. The LLM key stays on the operator `secrets:` path (SOPS).
3. ADR-073's acceptance gate gets its own staging PR (sealing key from SOPS,
   offline-sealed probe decrypts, rerun unchanged).
4. NetworkPolicy before the deploy: deny by default, ingress from Traefik,
   egress to DNS, the LLM API and the job boards.
5. Hostnames `resume.kubelab.live` and `resume.staging.kubelab.live`, with a
   narrow D8 amendment.
6. Image `ghcr.io/mlorentedev/resume`, private, GHCR pull credential (#2884).
7. Reuse notify-router (#1961), Grafana/Loki alerting, the R2 node backup.
8. Staging holds fixture data only; prod holds real data later.

## Audit (what was read, what was not)

- ADRs read in full: ADR-038, ADR-061, ADR-062, ADR-067 (with the D2 amendment),
  ADR-073; ADR-047 in part; IDP-053 proposal, tasks and verification. The ADR
  corpus was not read end to end; these are the ADRs this change touches.
- Code read: `toolkit/features/product_contract.py`, `product_guards.py`,
  `product_render.py`, `generator_k8s.py`, `k8s_secrets.py`,
  `secrets_manager.py`, `infra/config/products.yaml`,
  `infra/k8s/templates/deployments.yaml.j2`,
  `infra/k8s/base/governance/networkpolicies.yaml`, the K8s Authelia
  `configuration.yml` (base and prod overlay), `infra/ansible/roles/node_backup`,
  `common.yaml` (`cluster_bootstrap`, `backup.sources`), and the gates
  `tests/test_stateful_service_classification.py`,
  `tests/test_alerting_emitter_window.py`, `tests/test_authelia_access_rules.py`,
  `tests/test_networkpolicy_coverage.py`.
- resume side: ADR-008 (`docs/adr/adr-008-host-the-control-surface-on-kubelab.md`)
  and `src/resume/web/app.py` (`/healthz` bypasses the host allow-list).
- Staging cluster, read on 2026-11-13: one node `ace1` (k3s v1.34.4), flannel
  plus k3s's embedded network-policy controller (no Cilium or Calico CRDs), the
  only StorageClass is `local-path` (RWO, `WaitForFirstConsumer`), and no
  sealed-secrets controller runs.
- Prod cluster: not readable in this session. Every prod fact is an open
  question below.
- Cross-project pattern library: not reachable in this session (no vault access
  from the authoring environment). No pattern was consulted; a reviewer with
  access should check the library for NetworkPolicy egress and SQLite backup
  patterns before slice E and the prod lane.

## Findings on the decisions (to confirm before slicing starts)

These do not reopen the owner's choices; they record where a decision, as
worded, does not match the system, and what this spec does instead.

**F1. There is no "resume namespace" (decision 4, reworded, not rejected).**
Every product renders into `kubelab` (`toolkit/features/generator_k8s.py:231`,
`namespace = "kubelab"`); ADR-067 D5's per-product namespaces are not built. A
namespace-wide default-deny in `kubelab` would cut every service. This spec
scopes the policy to resume's pods (`podSelector` on
`app.kubernetes.io/name: resume`, matching both the web pods and the CronJob
pods) with `policyTypes: [Ingress, Egress]`. A pod selected by a policy of each
type is default-deny in that direction, which is the property the owner asked
for. See Q1.

**F2. FQDN egress is not possible on this CNI (decision 4).** Plain
`NetworkPolicy` has no hostname rules, and the k3s embedded controller adds
none. The narrowest honest rule is in D7. HTTP-only (port 80) job boards fail
by construction. See Q2 (ruled).

**F3. The `VACUUM INTO` pre-step is redundant (decision 7).** `node_backup`'s
capture script (`infra/ansible/roles/node_backup/templates/node-backup-capture.sh.j2`)
already takes a WAL-consistent copy with `sqlite3 -cmd ".timeout 10000" ... ".backup"`
for any source declaring `pvc:` plus `sqlite:`, then ships it with restic to R2
(prod example: `backup.sources.vps.n8n`). A `VACUUM INTO` before it adds a
second copy and a second failure mode for the same guarantee. See Q3.

**F4. ADR-073 D9 names Litestream for `volume`; the owner chose node backup.**
ADR-073 D10 also makes restore verification and capacity admission "required by
v1". The acceptance PR (slice K) records both as amendments; resume's subset
defers them to the prod lane.

**F5. ADR-061 forbids a singleton rendering in both overlays.**
`test_no_singleton_renders_in_both_overlays` refuses a singleton's claims in
staging and prod, while resume's ADR-008 classifies resume as `singleton` and
wants staging on the same manifests with fixtures. This does not block the
first staging deploy (only staging renders), but it blocks prod onboarding. See Q4.

**F6. A 26-hour window over a daily job holds one sample.**
`tests/test_alerting_emitter_window.py` requires `MIN_SAMPLES = 2`. The rule
needs an `EXEMPT` entry whose reason cites the owner's decision. There is no
kube-state-metrics, so the rule reads a Loki log line: resume must print a
stable success marker (https://gitea.kubelab.live/personal/resume/issues/777).

**F7. Sealed Secrets is absent despite SEAL-001 (#372) being closed.** No
manifest, no `cluster_bootstrap` entry, no SOPS key and no running controller
exist. Slice A installs the controller; it is not only a key-verification PR.
`SecretMapping` has no `labels` field today (`toolkit/features/k8s_secrets.py`),
and the controller only adopts a key Secret labelled
`sealedsecrets.bitnami.com/sealed-secrets-key=active`, so slice A adds one.

**F8. Contract `secrets:` never reach a pod.** They are checked against
`SECRET_CATALOG` only. `generator_k8s._has_secret_vars` mounts `<app>-secrets`
only when a `SecretMapping` with that name exists in `k8s_secrets.py`. "The
existing operator path" therefore means a hand-written
`SecretMapping("resume-secrets", ...)` plus catalog entries (slice H).

**F9. IDP-053 S2b is unchecked in its `tasks.md`, but the pull Secret is
wired.** `deployments.yaml.j2` emits `imagePullSecrets` for a private entry and
`tests/test_image_pull_secret.py` exists. This spec treats the pull path as
present on master and does not depend on S2b's checkbox.

## Decisions

**D1. `schema_version` stays 1; `resources:` is optional and additive.** A v1
contract without `resources:` validates and renders byte-identically.
Rejected: bumping to 2 (forces every existing contract and the receiver to
migrate for a field none of them use).

**D2. Claim shape.** `resources: {<name>: {type, class?, params}}`, a
discriminated union on `type`, each member closed (`extra="forbid"`, strict).
Name pattern `^[a-z][a-z0-9-]{0,30}$`. `class` is optional with one accepted
value per type today (`volume: local`, `job: cron`); absent means that value.
Later ADR-073 types add union members; later params add optional fields. Both
are additive, so resume's `kubelab.yaml` keeps validating. The JSON Schema in
`toolkit/schemas/kubelab-product.schema.json` is regenerated from the model, and
a test asserts it matches.
Rejected: a free `params: dict` (no schema to publish, typos become runtime
failures); flat top-level `volume:`/`cronjob:` keys (not D3's shape, so the full
ADR-073 would break it).

**D3. `volume` params:** `size` (Kubernetes quantity), `mount_path` (absolute),
optional `fs_group` (int, 1..2^31-1; 10001 for resume). Renders one PVC
`<app>-<name>` on the env's default StorageClass, RWO.
Rejected for `fs_group`: deriving it from the image (needs a registry read at
render time), relying on local-path's 0777 (owner ruling 2026-11-04).

**D4. `job` params:** `schedule` (5-field cron), `command` (argv list),
`volume` (name of a declared volume claim), optional `active_deadline_seconds`
(default 3600). The renderer fixes `concurrencyPolicy: Forbid`,
`backoffLimit: 2`, `restartPolicy: Never`. The CronJob pod uses the app's image,
ConfigMap, `<app>-secrets` (when mapped), pull Secret and the named volume.
Co-location comes from the local-path PV's node affinity, with no pod affinity
(owner ruling Q1(A), 2026-10-22). The contract holds one `schedule`, and every
env runs it, staging included (owner ruling, 2026-11-14).
Rejected: a per-env schedule override on the registry entry, and a suspended
staging CronJob with a one-off run (the owner accepts staging's spend at the
contract's schedule; see Risks).
Rejected: a shell line in `kubelab.yaml` instead of `resume daily` (#2366
status; https://gitea.kubelab.live/personal/resume/issues/777).

**D5. A Deployment that mounts a volume claim uses `strategy: Recreate`.**
Today's template is `RollingUpdate`, `maxUnavailable: 0`, `maxSurge: 1`; a surge
pod cannot open a WAL database the old pod still holds, and on a multi-node
cluster it could not mount the RWO volume at all. Cost: seconds of downtime per
deploy on a single-replica admin tool. Every pod mounting the claim gets
`securityContext.fsGroup` and `fsGroupChangePolicy: OnRootMismatch`.

**D6. Claims render from the env snapshot, not from values.**
`_extract_app_env_vars` flattens `apps.platform.<app>.*` into ConfigMap env
vars, so claims pushed through `CONTRACT_KEYS` would leak into the pod
environment. The renderer reads `infra/config/products/contracts/<app>.yaml`.

**D7. NetworkPolicy, generated only for products that declare `resources:`.**
Two policies on `app.kubernetes.io/name: <app>`:
- `<app>-ingress`: from Traefik (`kube-system`, `app.kubernetes.io/name: traefik`)
  on the container port.
- `<app>-egress`: the profiles listed on the product's registry entry
  (`infra/config/products.yaml`, `egress: [...]`), never in the contract, so a
  product cannot widen its own network. Profiles:
  - `dns`: kube-dns (`kube-system`, `k8s-app: kube-dns`), UDP and TCP 53.
  - `public-https`: TCP 443 to `0.0.0.0/0` except `10.0.0.0/8`,
    `172.16.0.0/12`, `192.168.0.0/16`, `100.64.0.0/10`, `169.254.0.0/16`.
  - `notify`: n8n pods on TCP 5678, plus the reciprocal `from` on
    `n8n-ingress`. resume must call `http://n8n:5678/webhook/notify`; the public
    `n8n.<env>.kubelab.live` resolves to a private address and is blocked.

`web` keeps its hand-written policy, byte-identical. This is the cluster's first
egress restriction; NET-002 (#378) stays open for every other workload.
Rejected: Cilium (a CNI swap for one product), an egress proxy with a domain
allowlist (a new always-on component and a new failure mode), a namespace
default-deny in `kubelab` (cuts every service; F1).

**D8. `forwardauth-admins`.** A new `auth:` literal. `product_render` maps it
to `enable_auth: true`, `auth_level: one_factor` and the group `admins`. The
Authelia rule is hand-added to the static config in the onboarding PR with
`subject: group:admins`, and a test asserts that every host of a
`forwardauth-admins` product has exactly that subject. `owners:` stays
identities (owner ruling Q2(A)).

**D9. D8 amendment (IDP-053) in `check_staging_hostname`.** The apex is derived
from `WILDCARD_ZONE` (`staging.kubelab.live` → `kubelab.live`). If the declared
prod hostname is exactly one label under the apex, and that label is not
`staging`, staging must be `<label>.staging.kubelab.live`. Any other prod
hostname keeps today's rule (`staging.<prod>`). A contract with `hostnames.prod`
but no `events.prod` renders for staging. ADR-067's D2 amendment gets a dated
note.
Rejected: `staging.resume.kubelab.live` (falls under prod's cookie domain;
staging Authelia scopes to `staging.kubelab.live`, #1805).

**D10. ADR-061 gate attributes generated claims by label.** The classification
test resolves the owner from `app.kubernetes.io/name` and the config block from
`apps.platform.<app>`, so a generated `claims.yaml` is not attributed to a
service named `claims`.

**D11. Backup.** The prod lane declares
`backup.sources.vps.resume: {pvc: {namespace: kubelab, claim: resume-data},
sqlite: [scan-history.sqlite, tracker.sqlite, evaluations.sqlite,
embeddings.sqlite]}` and no pre-step (F3; owner ruling Q3 = A). Each store is
copied by its own `sqlite3 .backup`, one after another, so each copy is
consistent on its own but the set is not a single point in time: the copies
can be seconds apart, and a daily run that writes during the capture can leave
one store a step ahead of another. The prod restore drill (Q8) restores the
set from R2 and checks that resume opens it and that cross-store references
resolve. Staging (`ace1`) has no backup sources and holds fixtures, so nothing
is declared there.

**D12. Notifications and alerting.** resume posts
`{domain, severity, title, body, source}` to notify-router in-cluster with the
bearer `apps.services.automation.notify.webhook_secret`, mapped into
`resume-secrets`. The no-success alert is a Loki rule on resume's success
marker over schedule period plus 2 hours (26h for daily), with an `EXEMPT`
entry (F6).

## Acceptance criteria

Deployed properties are marked (deployed); the rest are checked from the diff.

- AC1. `uv run pytest tests/test_product_contract.py tests/test_product_contract_guards.py`
  passes, including: a v1
  contract without `resources:` validates; one with a `volume` and a `job`
  validates; an unknown type, an unknown param, a `job.volume` naming no
  declared volume, and a duplicate name are each refused with the field named.
- AC2. The committed JSON Schema equals the one generated from the model
  (`uv run pytest tests/test_product_contract_schema.py`).
- AC3. Every existing product renders byte-identically: `make validate-sync`
  (the ADR-027 drift check) passes on slices B to F before resume is onboarded.
- AC4. Rendering resume for staging produces one PVC, one CronJob with
  `concurrencyPolicy: Forbid`, `backoffLimit: 2` and an `activeDeadlineSeconds`,
  a Deployment with `strategy: Recreate`, `fsGroup: 10001`, the volume mounted at
  the declared path in both pods, and `imagePullSecrets: [pull-ghcr-io]`.
- AC5. `uv run pytest tests/test_stateful_service_classification.py` passes with
  resume's claims attributed to `resume`.
- AC6. `uv run pytest tests/test_product_staging_hostname.py` passes:
  `check_staging_hostname` accepts `resume.kubelab.live` with
  `resume.staging.kubelab.live`, refuses `staging.resume.kubelab.live` for that
  prod, still requires `staging.<domain>` for an own-domain product, and refuses
  prod `kubelab.live` and prod `staging.kubelab.live` paired by the new rule.
- AC7. `uv run pytest tests/test_networkpolicy_coverage.py
  tests/test_authelia_access_rules.py` passes with resume's web and CronJob pods
  selected and resume's host carrying `subject: group:admins`.
- AC8. Sealed Secrets on staging (deployed): after
  `toolkit secrets apply --env staging` and `toolkit infra k8s bootstrap --env staging`,
  exactly one Secret in the controller's namespace carries the active-key label;
  the fingerprint of `kubeseal --fetch-cert` equals that of the SOPS-held cert;
  the probe `SealedSecret` decrypts and its value's sha256 matches the expected
  digest (the value is never printed); a second run of both commands reports
  nothing changed.
- AC9. The staging pod reaches `Ready` on `GET /healthz` (deployed).
- AC10. `curl` to `https://resume.staging.kubelab.live/` with an `operator`
  Authelia session cookie gets 403 and with a `superadmin` session gets 200;
  without a session it redirects to Authelia (deployed; ADR-062 D5 live
  verification).
- AC11. From the resume pod, TCP 443 to a public job board succeeds, TCP 443 to
  a `10.0.0.0/8` service address and TCP 80 to a public host fail, and
  `http://n8n:5678/webhook/notify` answers (deployed).
- AC12. A manually created Job from the CronJob (`kubectl create job --from`)
  completes, prints the success marker, and the Grafana rule evaluates normal
  (deployed). Run once as an acceptance step, not as an operating procedure.

## What cannot be verified from a diff

| Property | Why | Where it is checked |
|---|---|---|
| The controller adopts the SOPS key | Controller behaviour at startup | AC8, staging |
| kube-router enforces egress `except` blocks | CNI implementation | AC11, staging |
| `fsGroup` applies on local-path | Kubelet and provisioner | AC9, the web pod writes `/data` |
| Authelia matches the group subject | Live config | AC10 |
| The success marker reaches Loki | Log pipeline | AC12 |

## Risks

- kube-router's handling of `ipBlock.except` is unverified on this cluster; AC11
  is the check, and slice E ships with an explicit rollback (delete the egress
  policy) if it over-blocks.
- `Recreate` gives a short outage per deploy; acceptable for an admin tool.
- The first egress restriction in the cluster may surface missing egress rules
  only resume needs (for example a provider that serves over a non-443 port).
- Staging uses the prod LLM key (Q6 = B), so staging spend draws on prod's
  provider budget, and a runaway staging job can exhaust it for prod. Staging
  runs the contract's own schedule; the owner accepts this risk ("there is
  margin", 2026-11-14). What bounds a single run is the job's
  `activeDeadlineSeconds` and `concurrencyPolicy: Forbid` (D4). The key is
  shared, so a leak from staging is a prod leak; it is mapped only into
  `resume-secrets` and never into the ConfigMap (slice H test).

## Owner rulings

Recorded from the owner, relayed on #3476. "Pending owner objection" marks a
recommendation taken as the working position until the owner says otherwise.

**Q1. Policy scope: (A), pending owner objection.** Pod-scoped policies in
`kubelab` selecting resume's pods (D7). Rejected: (B) build ADR-067 D5's
per-product namespaces first, then a namespace default-deny; it is a
fleet-wide change far larger than this spec, and (A) gives resume the same
default-deny now.

**Q3. Backup pre-step: (A), ruled.** Reuse `node_backup`'s `sqlite3 .backup`,
no `VACUUM INTO` (F3). The per-store copies can be seconds apart; see D11.

**Q4. ADR-061 and the staging twin: (A), pending owner objection.** A narrow
ADR-061 amendment: a singleton may render in staging when its entry declares
`staging_state: fixtures`, and the duplication clause accepts it. Rejected:
(B) classifying resume as `dual`, which misclassifies its prod state to pass a
test. Needed before prod, not before staging.

**Q5. Seeding staging fixtures: (A), ruled.** resume seeds fixture data itself
when `/data` is empty and its seed setting is on (staging values only), tracked
as https://gitea.kubelab.live/personal/resume/issues/810. Rejected: an init
container copying fixtures from the image (platform code for a product
concern); `kubectl cp` (a manual operation).

**Q2. Egress rule: (A), ruled.** `public-https`: TCP 443 to anything outside
the private, carrier-grade NAT and link-local ranges (`10.0.0.0/8`,
`172.16.0.0/12`, `192.168.0.0/16`, `100.64.0.0/10`, `169.254.0.0/16` in
`except`), plus `dns` and `notify` (D7). Threat model:
- Closed: lateral movement. A compromised resume pod cannot open connections to
  cluster services, node addresses, the home LAN, the Tailscale/Headscale mesh
  (`100.64.0.0/10`) or cloud metadata (`169.254.0.0/16`), except DNS and n8n's
  webhook port.
- Not closed: exfiltration to a host of the attacker's choosing on the public
  internet over 443. The policy cannot tell a job board from any other public
  address.
- Known cost: HTTP-only (port 80) job boards are unreachable.

Upgrade path: (B), an egress proxy with a domain allowlist, if exfiltration
becomes part of the threat model or a domain allowlist becomes a requirement.
(C) a CNI with FQDN policy is the alternative at the cluster level. Rejected
now: (B) adds an always-on component and a new failure mode; (C) swaps the CNI
for one product.

**Q6. Staging LLM key: (B), ruled.** Staging uses the prod key and runs the
contract's own schedule; the owner accepts the shared-budget risk (Risks).
Rejected: (A) a separate capped key; (C) a suspended staging CronJob; a
per-env schedule override.

**Q8. Restore verification (ADR-073 D10): (A), pending owner objection.**
Deferred to the prod lane, with a restore drill from R2 before real data lands;
the drill also checks the cross-store consistency named in D11. Rejected: (B)
requiring it for staging, which holds fixtures only.

## Open questions (owner)

**Q7. Prod facts (prod cluster unreadable here).** Which node hosts resume in
prod, and is it `vps`? Is the `resume.kubelab.live` DNS record to be created by
the prod onboarding PR? #3286 (no pull credential on prod promotion) blocks the
prod lane; confirm it stays the prod-lane gate.

## Out of scope

The prod lane (prod onboarding, prod backup source, DNS, #3286); Sealed Secrets
on the product path; every other ADR-073 claim type; per-product namespaces;
the receiver trigger (IDP-053 S7); #3447; NET-002 for other workloads.

## Revisit when

- The cluster moves to a CNI with FQDN policy, or exfiltration to a public
  host enters the threat model: replace `public-https` with a domain allowlist
  (CNI rule or egress proxy; Q2).
- A second product declares a `volume` on a multi-node cluster: revisit D5 and
  the absence of pod affinity.
- ADR-067 D5 namespaces are built: move the policies to a namespace default-deny.
