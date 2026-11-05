---
id: "adr-074"
type: adr
status: proposed
owner: manu
date: "2026-11-05"
issue: "kubelab#2477"
tags: [architecture, decision, console, api, frontend, auth]
depends_on: [adr-050-cross-context-command-center, adr-053-platform-product-repos, adr-054-web-runtime-config, adr-056-build-once-monorepo-apps, adr-057-kubelab-api-boundaries, adr-066-self-hosted-task-platform, adr-067-product-contract-and-agent-access, adr-071-idp-branding-substrate, adr-073-self-service-resource-claims]
created: "2026-11-05"
---

# ADR-074: The Console Is Its Own Frontend App; the API Serves It on the Console Host Only

## Status

Proposed — 2026-11-05. Output of an `/architecture-session` on the operator console (CONSOLE-004, #2570). Answers the three questions #2477 left open:

- **Console:** decided (D1–D4).
- **REST surface and its authentication:** decided (D5, D6).
- **Product-facing CLI:** deferred, with reopen triggers (D9).

Decides what [ADR-066](adr-066-self-hosted-task-platform.md) A2 handed to this ADR ("a separate service for the view: rejected at the current scale, unless ADR-074 decides otherwise"). Reaffirms [ADR-050](adr-050-cross-context-command-center.md) D1's frontend shape (Astro + React islands) for the console, without reviving D1's ownership of board state, which ADR-066 A2 rejected.

## Date

2026-11-05

## Context

On 2026-11-04, `console.kubelab.live` became the forge view's address (#3107): a host of its own, guarded whole by Authelia. The API binary serves a read-only queue page there and answers `/console` on no other host.

The address is not under `/api` for a security reason. `mlorente.dev` proxies `PathPrefix(/api)` to the same Service with no authentication ([ADR-054](adr-054-web-runtime-config.md)), so an authenticated endpoint under `/api` would be one route change away from public.

That page was sized as a queue view: one embedded HTML file, no build step, about 80 lines. On 2026-11-05 the operator set the console's scope as the cockpit of the platform. Each piece below is sourced from the operator, from a peer lane, or from an accepted ADR:

- **Forge view:** a dense view over every forge, styled like Linear in the brand (ADR-071). It has tabs, filters held in the URL, keyboard navigation and pagination over thousands of items.
- **Pull request state:** a derived state for every pull request: CI red, pending or green; draft; conflicting; reviewer missing; triage owed; merged unreviewed; ready to merge.
- **Inbox reasons:** why an item needs the operator now.
- **Automations:** visible and triggerable, in the way Linear and GitHub Projects workflows are. ADR-050 already recorded that retiring the board loses `add-to-project.yml` and `bitacora-status.yml`.
- **Notices:** a panel of what n8n and the bots send to Slack.
- **Product registry:** the module ADR-066 A7 and ADR-073 D11 assign to this console.

At that scope, three facts change what ADR-066 A2 and [ADR-057](adr-057-kubelab-api-boundaries.md) D2/D4 weighed:

1. **The toolchain is a different language's.** A component framework, Tailwind, self-hosted font subsetting and browser tests need a Node build. Inside `apps/api` that is a Node stage in a Go image. Its multi-arch build is rebuilt and re-promoted for every UI change ([ADR-056](adr-056-build-once-monorepo-apps.md)).
2. **The cadences diverge.** The UI is expected to change daily while the forge view is in use. The API carries the newsletter and the web's endpoints too, and ships on its own release-please line. ADR-057 D4's second trigger ("an independent deploy cadence") is met for the frontend. It is not met for the read model, the webhooks or the outbox, whose only consumer is this console and whose data lives in the API's Postgres tenant.
3. **A second frontend exists to compare against.** `web` (Astro 7, Tailwind 4, `subset-font`, Playwright and axe, static nginx, build-once) is the first. Choosing the same stack makes the golden path that ADR-053 §5 defers until the second or third product something that can be distilled rather than guessed.

### Reference audit

| Reference | What it is | What this decision takes from it |
|---|---|---|
| `web` (kubelab's first frontend product, ADR-053 pilot) | Astro 7 static + Tailwind 4 + `subset-font` + Playwright/axe, nginx, build-once | The stack, the self-hosted fonts and the test tools. The extraction to its own repo is not taken (D3). |
| `edge/errors` | Static nginx in the monorepo, brand stylesheet SSOT (ADR-071, ADR-072) | The brand tokens come from `toolkit sync branding`, not from new hex values. |
| Linear | Dense, keyboard-first issue view; workflows as declarative rules over issue state | Interaction density, `/` and single-key navigation, saved views. Its own store of issue state is not taken (ADR-066 A2). |
| GitHub pull request dashboard and Graphite inbox | Pull requests grouped by why they need the viewer: review requested, CI failing, ready to merge | The inbox-reason and pull-request-state vocabulary (D7). |
| Backstage | Plugin portal over many backends | Nothing; rejected for one operator (ADR-026, rejection list). |

A search of the pattern library (`00_meta/patterns/`) found no frontend or dashboard pattern. `pattern-build-once-promote-by-digest` applies to the console image unchanged.

## Options considered

| Option | Door | Verdict |
|---|---|---|
| **A. Keep the UI inside the API binary** (embedded HTML, or htmx with Go templates) | Two-way | Rejected at cockpit scope. It fits a read-only queue page. It puts a Node stage, or a hand-written component system, in the Go image, and couples every UI change to an API release. Reopen if the console shrinks back to one read-only page. |
| **B. `apps/console`, its own app in this repo: Astro static + React islands + Tailwind 4, served by nginx, same-origin with the API on the console host** | Two-way (stack), one-way (auth model, D6) | **Chosen.** |
| C. `apps/console` as a Vite + React single-page app | Two-way | Viable, and close to B in practice since most pages are one island. Not chosen: it forks the toolchain from `web` (fonts, tests, Tailwind config, CI job), so the golden path would have two shapes after two products. Reopen if islands get in the way of the client state the console needs (D4). |
| D. A separate repository now | One-way-ish (cross-repo promotion, governance) | Rejected now. The product lifecycle in `CLAUDE.md` incubates in this monorepo first, and ADR-053 §5 says not to design the extracted template from one data point. Extraction trigger in D3. |
| E. An off-the-shelf tracker or portal (Vikunja, Plane, Backstage) | — | Already rejected: ADR-066 (2026-10-20 amendment) and the Backstage row of the rejection list. |
| F. Grafana as the console | — | Already rejected: Grafana holds no ownership and opens no actions (ADR-073 D10, ADR-066). Statistics stay in Grafana, and the console links to them (D8). |

## Decision

### D1 — Split by layer: the backend stays in `apps/api`, the frontend is `apps/console`

The forge read model, the webhook receiver, the reconcile, the outbox, the narrow writes and the derived pull-request state stay a module of `apps/api`, as ADR-066 A2 placed them. ADR-057 D5 forbids a second API, and D3 allows a single-consumer module there while it stays a clean package.

The frontend leaves the binary and becomes `apps/console`, a custom app beside `api`:

- its own image, `kubelab-console`, built once and promoted by digest like `kubelab-api` (ADR-056);
- its own Deployment and its own release-please tag line, `console-vX.Y.Z`;
- its own CI path filter.

The embedded page from #3107 is transitional. It is deleted when `apps/console` serves the same view.

### D2 — Stack: Astro static + React islands + Tailwind 4, the same toolchain as `web`

- **Rendering:** static output served by nginx (`nginx-unprivileged`, read-only root). Interactive views are React islands. There is no server rendering, so the console adds no Node process at runtime.
- **Brand:** `toolkit sync branding` projects the ADR-071 tokens into the console's Tailwind theme as well as into `brand.css`, under the same `--check` drift gate. No hex value is written in `apps/console`.
- **Fonts:** Inter and JetBrains Mono are subset and served by the console itself. `secure-headers` allows `font-src 'self' data:` only, so no font CDN is introduced.
- **Look:** dark first, dense, keyboard-first.
- **Tests:** Playwright for behaviour and axe for accessibility, as in `web`.

### D3 — The console incubates in this repository

It is a platform frontend at the "incubating" stage of the product lifecycle. Its manifests live in `infra/k8s` like every other app's (ADR-053 §1).

Extract it to its own repository when any of these holds:

- a second product ships its own UI against this API;
- the console's development loop needs something the monorepo cannot give;
- the console needs an owner or a release process separate from kubelab's.

Until then, the toolkit pays a bounded cost for a third custom app: `deployment promote`'s app list, the K8s generator's app set and `default_port` overrides, the CI path filters and a Node job.

### D4 — Client state is fetched, not stored

The console holds no state a forge or the API holds (ADR-066 A2, A3). Islands read the API with a cache-and-revalidate client and keep only view state (filters, sort, selection) in the URL, so every view is a link. Saved views are named URLs, kept per operator in the API's store. They are the one thing the console persists, and they hold no item data.

### D5 — One origin: nginx at `/`, the API under `/console/` on the console host

On `console.kubelab.live` (and `console.staging.kubelab.live`), Traefik sends `PathPrefix(/console/)` to the API Service and everything else to the console's nginx. Both rules carry the `authelia` ForwardAuth.

The API surface for the console lives under `/console/` and nowhere else:

- It is never under `/api`. That keeps two independent layers between it and the public host: `mlorente.dev` never forwards `/console/` at all, and the API answers `/console/` only when the Host header is the declared console host (`INFRA_FORGE_CONSOLE_DOMAIN`, #3107).
- No CORS is configured, because nothing is cross-origin.
- The existing `/console/queue` keeps its path. New endpoints are added under the same prefix.

### D6 — Authentication: Authelia at the edge, the identity in `Remote-User`, trusted on the console host only

- **Where authentication happens.** Every request to the console host passes the `authelia` ForwardAuth, whose `authResponseHeaders` set `Remote-User`, `Remote-Groups`, `Remote-Email` and `Remote-Name`. Traefik overwrites any value a client sent for those headers.
- **Trust rule:** the API reads `Remote-User` only in handlers behind the console host guard. On any other host the header is client input and is ignored.
- **Why that rule is sufficient.** The NetworkPolicy admits only Traefik to `api:8080`. `tests/test_console_route_auth.py` already fails if any rule for the console host lacks `authelia`, so every request that reaches a console handler has been authenticated.
- **Writes.** Every write is attributed to `Remote-User` (C22). A request with no `Remote-User` is refused, which fails closed if the middleware is ever dropped.
- **Machine identity.** Exactly one machine route is planned: the create write called from Slack (ADR-066 A4). It authenticates with its own token from SOPS, and every other route refuses that token (CONSOLE-004 task).
- **The ADR-067 reopen trigger.** Option E ("a consumer needs REST rather than MCP") is not reopened. The console is a browser behind Authelia reading its own module, not an agent gateway. Agents keep MCP.
- **#2477's two preconditions.** "No REST surface before API authentication" is met for this surface by the host guard plus ForwardAuth; it is not a general API authentication, and no other surface may rely on it. "A stale generated file fails CI" is met by `tests/test_sync_platform_json.py`. The conflict churn on `platform.json` is #1860, open.

### D7 — The console's model: items, derived pull-request state, inbox reasons, notices, automations

The API derives each of the following and exposes them under D5. The console renders them; it computes none of them.

- **Pull-request state.** One value per open pull request, in this order of precedence:

  | Precedence | State |
  |---|---|
  | 1 | conflicting |
  | 2 | CI red |
  | 3 | reviewer missing |
  | 4 | triage owed |
  | 5 | CI pending |
  | 6 | draft |
  | 7 | ready to merge |

  "Merged unreviewed" is shown on merged pull requests.
  - **Sources:** forge pull-request reads; check runs and commit statuses; review comments; the `## Review triage` marker (the contract `dotf pr triage-queue` reads); the unreviewed declaration of the shared `pr-agent.yml`.
  - **Operator step:** the GitHub App `kubelab-console` reads Issues, Pull requests and Metadata today. It needs **Checks: read** and **Commit statuses: read** added and the installation's acceptance before this slice ships.
- **Inbox reasons.** Mine; review requested from me; CI red on mine; triage owed on mine; rollout pull requests waiting on the owner (the `ci/bitacora-workflows` pull requests that `bitacora-rollout.sh` opens). An item can carry several reasons. The JSON already leaves room for a `reasons` field (#3107).
- **Notices.** What reaches Slack is read where it passes, never from Slack. Two candidate taps:
  - a fan-out from n8n's `notify-router` into the API, recorded as events;
  - Grafana's alert state history in Loki (OBS-042 AC3, #2929).

  The choice is made with the OBS-042 lane. Reading Slack back would need a Slack read token and a third party in the path, so it is rejected.
- **Automations.** The rules live in n8n, as `notify-router` and the forge flows do (ADR-044, ADR-050 D2). The console contributes three things:
  - each event the API records (a webhook projected, a write confirmed) is emitted to a declared n8n webhook;
  - the console shows which automation acted on an item, read from the event record;
  - the console triggers a declared flow by name.

  The API does not grow a rules engine. Replacing the board's lost automations (`add-to-project.yml`, `bitacora-status.yml`) is the first set of rules, gated on ADR-066 A4's board step.

### D8 — Modules and boundaries

The console has two modules (ADR-066 A7):

- **Forge view.** Built first.
- **Product registry.** Built later. It reads what the toolkit writes to git (ADR-073 D11) and links into Argo CD, Grafana, logs and runbooks.

Statistics (throughput, queue age, time to first review, time with CI red) stay in Grafana over a counts-only view (CONSOLE-004 AC6), and the console links to them.

The LLM chat and per-context routing (ADR-050 D5) are out of scope and stay with #2494.

### D9 — Product-facing CLI: deferred

Whether a developer-facing CLI is part of `dotf` or a separate static binary is not decided here. Nothing the console needs depends on it. Reopen when:

- a product repository needs `init`, `validate` or `status` without the Python toolkit installed;
- or the API's REST surface grows a route meant for a non-browser consumer.

## Consequences

### Positive

- **The UI ships at its own pace.** It is no longer rebuilt into the API image, and an API release no longer carries UI risk.
- **Two products share one frontend stack**, so ADR-053 §5's golden path can be distilled from `web` and `console` together.
- **Two layers for one boundary.** The authentication boundary is drawn once: one host, one prefix, one middleware. It rests on two independent layers (the router, and the host guard in the API), and a committed test covers each.
- **The pull-request state is defined in one place.** The operator cockpit reads the vocabulary from the API (D7) instead of each view re-deriving it.

### Negative

- **A third custom app costs toolkit work** (D3) and a Node job in CI.
- **One more image and Deployment on the always-on host.** A static nginx is a few tens of MiB. It is stated against the VPS memory budget when the Deployment is written (C11: no new recurring cost).
- **The development loop needs an auth path.** Authelia's cookie is scoped to the console host, so `astro dev` on `localhost` cannot call staging's `/console/` with a session. The first `apps/console` slice provides a dev proxy that forwards to staging with the operator's session cookie, or a fixture mode, and states which (ADR-053 §4 requires an inner loop).
- **More work inside the CONSOLE-004 timebox.** ADR-066 A8's kill criteria stand: if the console is not opened on at least 5 of 14 days, the setup reverts. The usage counter A8 describes ships no later than the first `apps/console` slice, and further frontend work is gated on the counter showing use.

### Neutral

- The embedded page from #3107 stays until `apps/console` replaces it, then is deleted with its route.
- The portfolio's `kubelab-console` entry, which still describes a Quartz knowledge base, is corrected. `docs/architecture/components/kubelab-console.md` is rewritten to match this ADR.

## Sequence

Each step is one pull request unless noted. Steps 1 and 2 are API slices that need no frontend app.

1. Keyset pagination on `GET /console/queue` (`updated_at, id` cursor). The 500 limit becomes the page size, and the response says how many items exist.
2. A8 usage counter: a daily row per operator identity from `Remote-User` (ADR-066 A8).
3. `apps/console` scaffold, image, Deployment and routes:
   - routes under D5; brand projection and self-hosted fonts under D2;
   - the forge view at parity with the embedded page;
   - a dev loop with fixtures;
   - the embedded page deleted.
4. The Linear-style forge view:
   - tabs for All, Pull requests and Issues, with counts;
   - filters by repository, label, author and state, held in the URL;
   - `/` and single-key navigation;
   - freshness per source, amber when stale;
   - "N of M" when the page does not hold everything;
   - saved views.
5. Pull-request state (D7). The GitHub App permission change is the operator's step.
6. Inbox reasons (D7), including the ci-workflows signals recorded on #2570.
7. Notices panel (D7), after the tap is agreed with the OBS-042 lane.
8. Narrow writes and the outbox (ADR-066 A2), Slack `/task create` re-pointed (ADR-066 A4).
9. Automations (D7): event emission to n8n, the "acted on by" record, flows triggered by name; the board's automations as the first rules.
10. Product registry module (D8, ADR-073 D11).

Parallel work that remains on CONSOLE-004's task list:

- registering the webhooks;
- the Gitea source;
- the Grafana statistics;
- the restore rehearsal;
- the runbook;
- the end-to-end probe.

## References

- #2477 (this decision), #2570 (CONSOLE-004), #3107 (console host), #3068 (webhook source filter), #2929 (OBS-042), #2494 (ADR-050 D5), #1860
- ADR-050, ADR-053, ADR-054, ADR-056, ADR-057, ADR-066 (2026-10-20 amendment: A2, A4, A7, A8), ADR-067 (option E), ADR-071, ADR-073 (D10, D11)
- `specs/CONSOLE-004-forge-task-view/proposal.md` ("The console")
