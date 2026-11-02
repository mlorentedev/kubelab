---
id: lesson-616-one-snapshot-for-two-envs-that-advance-separately-makes-the-slower-one-drift
type: lesson
status: active
created: "2026-10-21"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, idp-042, product-contract, drift]
---

# One snapshot for two environments that advance separately makes the slower one drift

**Context**: IDP-042 renders a product's `kubelab.yaml` into `apps.platform.<app>` for
staging and prod, and keeps a committed copy, `infra/config/products/contracts/<app>.yaml`,
that the drift tests compare both environments against. The generic receiver writes that
copy and renders staging on every image. Prod is promoted later, by a human, through
`promote-prod.yml`.

**Problem**: The closeout review (FAIL, 2026-10-21) found that a contract change to a key prod
owns (`port`, `health_path`, `auth`, `hostnames.prod`) could not land. The receiver rewrote
the one snapshot and rendered staging, so `test_the_web_snapshot_matches_the_values[prod]`
went red on the staging deploy PR and stayed red on master, and no workflow rendered prod.
Both environments read one file, but they run different commits of the product: staging the
newest image, prod the last release. The proposal also said the prod lane should read "the
staging pin". That was wrong too. The staging deploy PR is long-lived, so the staging pin can
lag or lead the release: on the day of the fix staging pinned `sha-ceaffd5` while prod ran
`1.16.1` (`661a205`).

**Solution**: Each environment gets its own snapshot. `product_render.snapshot_path(app, env)`
answers `<app>.yaml` for staging and `prod/<app>.yaml` for prod, and every reader goes through
it: the drift tests, `render`'s `--app` inference, `snapshot_gaps` and `verify-product`.
`promote-prod.yml` gained a step that runs
`toolkit product release-contract --app <app> --version <v> --out contracts/prod/<app>.yaml`
and then `product render --env prod --write`. The command resolves the release tag `v<version>`
to a commit on the product's repository. It then requires `<image>:<version>` and
`<image>:sha-<commit7>` to share one digest, so the tag is proven, not trusted. Only after that
does it fetch and validate `kubelab.yaml` at the commit. Live on 2026-10-21: `1.16.1` →
`661a205a`, digest `sha256:95482d9a…` on both tags. The prod snapshot it wrote is byte-equal
to the staging one. `tests/test_product_contract_drift.py::test_a_contract_change_to_a_prod_owned_key_leaves_the_tree_green`
holds both halves, and it goes red under `make mutate` when prod is pointed back at the flat
file.

**Rule**: A committed copy of an input is per consumer that advances on its own schedule.
When two environments render from one source at different times, one shared snapshot makes
the drift check judge the slower environment against the faster one's input. And "the
version staging validated" names an image, not a commit of the current staging pin. Derive
the commit from the artifact being promoted, and prove the link by digest.

**Tags**: `#idp-042` `#product-contract` `#drift` `#adr-056`
