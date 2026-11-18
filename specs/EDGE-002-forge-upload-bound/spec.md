---
id: EDGE-002-forge-upload-bound
type: spec
status: draft
created: "2026-11-14"
owner: manu
issue: "kubelab#3550"
---
# EDGE-002: Forge upload bound

## Intent

A request body that takes more than 60 s to reach prod Traefik is cut. The cause is the `websecure` entrypoint's read deadline: Traefik v3 defaults `respondingTimeouts.readTimeout` to 60 s, and nothing in the repo declares it.

Measured on 2026-11-14 in prod Traefik's per-line access log for the gitea router (#3550):

- Every 499 is a `PUT` ending at `total` ≈ 60 s from the request start (60.0 to 61.2 s).
- The paired 504s are the same cut seen from the forward side: `total` ≈ 60 s, origin a few µs.
- They came in three bursts, 18:29, 20:02 and 20:34Z.

The first casualty is imagesensortool's multi-arch image push. Its arm64 base layers (25.9 MB, largest blob 17 MB) cross the edge at under about 2.3 Mbit/s, so the push fails. Master cannot publish, and prod's arm64 image waits on it.

The push crosses the edge only because of the path it takes:

1. Beelink CI resolves `gitea.kubelab.live` publicly.
2. The blob leaves the home uplink, reaches the VPS, and comes back over the tailnet to the Gitea on the same Beelink.

Any other upload longer than 60 s through the edge is cut the same way: a large git push, an LFS object, a release asset.

## Scope

Owner ruling 2026-11-14: option (c), both changes, in two PRs. Order ruled the same day: the local push (root fix) first. PR 2's value ruled: declare 60 s, no behaviour change, raised later only on a measured off-LAN failure.

**PR 1: CI pushes to the registry without crossing the edge (root cause).**

- Job containers already join the `kubelab` compose network (`act-runner-config.yaml.j2`, `container.network`), where Gitea answers at `gitea:3000`. The push is not made by the job container, though. It comes from the BuildKit container that setup-buildx starts, and that container is not on the network. The mechanism therefore sits in the product's workflow:
  - attach BuildKit to `kubelab` (`driver-opts: network=kubelab`);
  - mark the endpoint plain HTTP (`[registry."gitea:3000"] http = true`);
  - point login and tags at it.
  The traffic stays on one host's bridge network, as `actions/checkout`'s already does.
- **Blobs stay local; the token does not.** Read at source for Gitea 1.27.3:
  - Every upload `Location` is relative (`routers/api/packages/container/container.go`), so blob PUTs go to whatever host the client used.
  - The token realm comes from `GuessCurrentHostURL`. Kubelab pins `PUBLIC_URL_DETECTION: legacy` (`compose.yml.j2`), and a request with no `X-Forwarded-Proto` then falls back to `ROOT_URL`. The token GET therefore still goes to `https://gitea.kubelab.live/v2/token` through the edge.
  - That GET is small, so it survives the 60 s bound, but the push still needs the edge to be up. Changing `PUBLIC_URL_DETECTION` is out of scope.
- **Pull references are unaffected.** Kubelab composes them from `products.yaml` `image_registry` (`gitea.kubelab.live/personal`), not from the push host. Both names point at the same storage.
- **Prove it before codifying.** A throwaway imagesensortool branch pushes a scratch tag with the literals above. It is accepted when the 17 MB blob completes and the per-line query on #3550 shows no gitea `PUT` for that run. That run is also imagesensortool's unblock. Kubelab's PR then replaces the literals with a declared endpoint: `common.yaml`, handed to jobs by act_runner if its pinned config schema has `runner.envs`, and named in the docs.

**PR 2: declare the entrypoint read bound (`readTimeout`).**

- The `k3s_server` role defaults declare the bound for the `websecure` entrypoint, rendered into `additionalArguments`, the same way as `k3s_traefik_response_header_timeout` (ADR-076). A test fails if the rendered flag and the declaration diverge.
- ADR-076 gets an amendment for the client side. It records:
  - Traefik has no per-router read bound, so any value applies to every route on the entrypoint;
  - the only finer alternative is a second entrypoint;
  - what the value is sized for.
- The value is an owner ruling: 60 s, ruled 2026-11-14.

**Out of scope:**
- A local TLS terminator for `gitea.kubelab.live` on the Beelink.
- A second entrypoint.
- Changing ADR-076's header bound.

## Checklist

- [x] PR 1: throwaway imagesensortool run pushes a scratch tag to `gitea:3000` (BuildKit on `kubelab`, `http = true`): the 17 MB blob completes and no gitea `PUT` shows on prod Traefik for that run.
- [x] PR 1: declare the endpoint in common.yaml and hand it to jobs through `runner.envs` (supported by the pinned `gitea/runner:4.1.0`).
- [x] PR 1: owner runs the Beelink provision, which restarts act_runner: no job running; a job prints the variables.
- [x] PR 1: runbook and product-onboarding docs name the variable; imagesensortool's workflow switches (its repo); its master push goes green.
- [x] PR 2: declare `readTimeout` on `websecure` and render it with a test (red before, green after).
- [x] PR 2: reproduce the cut in staging (an upload of about 90 s through the staging edge: 499 at 60 s before, completes after, if the value is raised). Not applicable: the ruled value is 60 s, Traefik's default, so there is no before/after to reproduce.
- [x] PR 2: ADR-076 amendment; owner runs the `k3s_server` role on the VPS (check mode first; it restarts the only Traefik replica, which fronts Headscale).

## Evidence

- Per-line prod Traefik read, 2026-11-14: recorded on #3550.
- Local-push proof, 2026-11-14: imagesensortool runs 3526 and 3532 pushed over `gitea:3000`, the 50 MB layer in 3.3 s, which the home uplink (under about 2.3 Mbit/s) cannot carry. Corroborated, within the access log's floor (1 s or 5xx), by prod Traefik's gitea `PUT` log read on 2026-11-15: none between 22:55 and 23:01Z, with the cut bursts before it as the control.
- Beelink provision (PR 1, #3592): applied `changed=2` (runner config and its recreate handler), re-run `changed=0`.
- imagesensortool switched to the recipe (personal/imagesensortool#205, `c3a40c3`, merged 2026-11-17T07:07Z). Runs 3620 (`c3a40c3`) and 3622 (`6db71aa`) green: BuildKit on `kubelab` with `[registry."gitea:3000"] http = true`, push step 1.8 s; the guard step's `test -n` on both variables passed, so the jobs received them; both platforms listed by `imagetools inspect` on the public name. Base blobs were already in the registry, so this is not a cold-push timing. Prod Traefik's gitea router logged no `PUT` from 07:00 to 07:19Z; its last `PUT`s were at 05:53Z, from the pre-switch run.
- VPS (PR 2, #3596), 2026-11-17: `make deploy TARGET=k3s ENV=prod TAGS=k3s-server` changed only the HelmChartConfig (`changed=1`), re-run `changed=0`; `make test-e2e ENV=prod` 78 passed, 31 skipped, 0 failed.

## Next

None. Both PRs merged and applied; the consumer is switched.

## Promotion candidates

- [x] Lesson? yes: docs/lessons/edge-tls/lesson-762-a-499-at-exactly-60-s-is-traefik-s-read-deadline-not-the-client.md
- [x] ADR? yes: docs/adr/adr-076-edge-backend-timeouts.md
- [x] Pattern? no: a single-repo edge setting; the lesson and the ADR amendment carry it.
