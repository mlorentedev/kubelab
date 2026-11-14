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

- Every 499 is a `PUT` ending at `total` = 60.000 s from the request start.
- The paired 504s are the same cut seen from the forward side: `total` ≈ 60 s, origin a few µs.
- They came in two bursts, 18:29 and 20:02.

The first casualty is imagesensortool's multi-arch image push. Its arm64 base layers (25.9 MB, largest blob 17 MB) cross the edge at under about 2.3 Mbit/s, so the push fails. Master cannot publish, and prod's arm64 image waits on it.

The push crosses the edge only because of the path it takes:

1. Beelink CI resolves `gitea.kubelab.live` publicly.
2. The blob leaves the home uplink, reaches the VPS, and comes back over the tailnet to the Gitea on the same Beelink.

Any other upload longer than 60 s through the edge is cut the same way: a large git push, an LFS object, a release asset.

## Scope

Owner ruling 2026-11-14: option (c), both changes, in two PRs. The order below (the root fix first) is proposed and still awaits the owner's ruling.

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

- `common.yaml` declares the bound for the `websecure` entrypoint, rendered through `k3s_server` into `additionalArguments`, the same way as `k3s_traefik_response_header_timeout` (ADR-076). A test fails if the rendered flag and the declaration diverge.
- ADR-076 gets an amendment for the client side. It records:
  - Traefik has no per-router read bound, so any value applies to every route on the entrypoint;
  - the only finer alternative is a second entrypoint;
  - what the value is sized for.
- The value is an owner ruling (see Next).

**Out of scope:**
- A local TLS terminator for `gitea.kubelab.live` on the Beelink.
- A second entrypoint.
- Changing ADR-076's header bound.

## Checklist

- [ ] PR 1: throwaway imagesensortool run pushes a scratch tag to `gitea:3000` (BuildKit on `kubelab`, `http = true`): the 17 MB blob completes and no gitea `PUT` shows on prod Traefik for that run.
- [ ] PR 1: declare the endpoint in common.yaml and hand it to jobs (`runner.envs` if the pinned act_runner supports it); owner runs the Beelink provision, which restarts act_runner: no job running.
- [ ] PR 1: runbook and product-onboarding docs name the variable; imagesensortool's workflow switches (its repo); its master push goes green.
- [ ] PR 2: declare `readTimeout` on `websecure` and render it with a test (red before, green after).
- [ ] PR 2: reproduce the cut in staging (an upload of about 90 s through the staging edge: 499 at 60 s before, completes after, if the value is raised).
- [ ] PR 2: ADR-076 amendment; owner runs the `k3s_server` role on the VPS (check mode first; it restarts the only Traefik replica, which fronts Headscale).

## Evidence

- Per-line prod Traefik read, 2026-11-14: recorded on #3550.

## Next

Get the owner's rulings, then start PR 1:
1. **The PR 2 value.** Either keep 60 s and only declare it (no behaviour change; PR 1 is the fix), or raise it for what still crosses the edge after PR 1: off-LAN git push, LFS, release assets. A raised bound lets a slow client hold a connection longer on every route. At the rate limit (30/s per host), the exposure is 30 × T open requests per host.
2. **PR 1 in imagesensortool:** the product's session makes the change once the variable exists.

## Promotion candidates

- [ ] Lesson? `yes`: Traefik v3's default `readTimeout` of 60 s cuts any request body longer than that, and the 499 it logs reads as a client abort.
- [ ] ADR? `yes`: ADR-076 amendment (PR 2).
- [ ] Pattern? `no`
