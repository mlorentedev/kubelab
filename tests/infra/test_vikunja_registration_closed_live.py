"""Infrastructure: Vikunja refuses public self-registration, on the LIVE host.

`tasks.kubelab.live` has a public Cloudflare record and its IngressRoute carries no
network restriction (ADR-066 D3 deliberately keeps Authelia ForwardAuth OFF, so REST
callers and webhooks reach the API with a Bearer token). That decision is correct and
must stay -- it is why this file asserts on the *registration* door specifically and
not on anonymous reachability, which is load-bearing here in a way it is not for Gitea.

Nothing in the repository declares `VIKUNJA_SERVICE_ENABLEREGISTRATION`, so Vikunja's
own default (`true`) applies and anyone who reaches the domain can mint an account.
This is the same shape as SEC-GITEA-001 (#1389) -- "safe only because there is nothing
inside yet" -- and the same expiry applies: ADR-066 makes this instance the bitacora
that replaces GitHub Projects, so it is about to hold the task state of every project.

Why an infra test and not a unit one: the failure mode is a pod running an older
ConfigMap than the one in git. `vikunja.env` is rendered through `configMapGenerator`,
so a content hash rolls the Deployment and that *should* be automatic -- but a merged
template is not a deployed one (lesson-404, #1548), and only the running instance
knows. The static half lives in `tests/test_vikunja_registration_declared.py`.
"""

from __future__ import annotations

import os

import httpx
import pytest
import yaml

pytestmark = pytest.mark.infra

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_COMMON_YAML = os.path.abspath(os.path.join(_REPO_ROOT, "infra/config/values/common.yaml"))

#: Vikunja advertises its own registration state here, unauthenticated. This is what
#: the web UI reads to decide whether to render the signup form.
INFO_PATH = "/api/v1/info"

#: The flag is NESTED under `auth.local`, not at the top level, in v1.0.0. Measured,
#: because a prior session recorded it as a top-level `registration_enabled` and there
#: is no such key -- reading `payload.get("registration_enabled")` would have been
#: falsy against a wide-open instance and reported it as closed. Kept as an explicit
#: path so a future Vikunja that moves the field fails the key check below instead of
#: silently answering `None`.
FLAG_PATH = ("auth", "local", "registration_enabled")

#: The actual door. `RegisterUser` in `pkg/routes/api/v1/user_register.go` returns
#: `echo.ErrNotFound` (404) when `service.enableregistration` is false, and falls
#: through to payload validation (400) when it is true. So the two states are told
#: apart by status alone, with no account created either way -- an empty body cannot
#: validate. Asserting on this as well as on the advertised flag matters because the
#: flag is a claim about the door and this is the door.
REGISTER_PATH = "/api/v1/register"


def _vikunja() -> dict:
    """The Vikunja service block, from the SSOT. Never a literal -- CLAUDE.md's rule."""
    with open(_COMMON_YAML, encoding="utf-8") as handle:
        common = yaml.safe_load(handle)
    return common["apps"]["services"]["core"]["vikunja"]


@pytest.fixture(scope="module")
def base_url() -> str:
    return f"https://{_vikunja()['domain']}"


@pytest.fixture(scope="module")
def info_payload(base_url: str) -> dict:
    """Guard the guard: skip when Vikunja is down, never pass vacuously.

    Without this, every assertion below would go green against an instance that is
    not running at all -- Traefik answers 502 through error-pages for an unreachable
    backend, and a 502 is neither 200 nor a registration form.
    """
    try:
        response = httpx.get(f"{base_url}{INFO_PATH}", timeout=15.0)
    except httpx.HTTPError as exc:
        pytest.skip(f"Vikunja unreachable at {base_url}{INFO_PATH} ({exc})")
    if response.status_code != 200:
        pytest.skip(
            f"Vikunja not healthy: {INFO_PATH} returned {response.status_code}, expected 200. "
            "Registration assertions would pass vacuously against an instance that is down."
        )
    return response.json()


def test_vikunja_advertises_registration_as_closed(info_payload: dict) -> None:
    """The advertised flag is `false`, and the key is present to say so.

    The key check is not ceremony, and it already earned its place: the field is at
    `auth.local.registration_enabled`, while a prior session recorded it as top-level.
    A `payload.get("registration_enabled")` would have been `None` -- falsy, therefore
    "closed" -- against the wide-open instance measured here. An empty expectation is
    not a weak expectation; it matches everything (lesson-416).
    """
    cursor: object = info_payload
    for depth, key in enumerate(FLAG_PATH):
        assert isinstance(cursor, dict) and key in cursor, (
            f"{INFO_PATH} has no `{'.'.join(FLAG_PATH)}`: stopped at "
            f"`{'.'.join(FLAG_PATH[:depth]) or '<root>'}`, which holds "
            f"{sorted(cursor) if isinstance(cursor, dict) else type(cursor).__name__}. "
            "This test cannot pass or fail meaningfully against this payload -- "
            "Vikunja may have moved the field. Fix the guard before reading its "
            "result as a finding."
        )
        cursor = cursor[key]

    assert cursor is False, (
        "Vikunja advertises public self-registration as OPEN on an internet-facing "
        "domain. Anyone who reaches it can mint an account. Declare "
        "`VIKUNJA_SERVICE_ENABLEREGISTRATION=false` in "
        "`infra/k8s/base/services/vikunja-config/vikunja.env` (prod inherits it via "
        "`behavior: merge`), then confirm the pod actually rolled -- a ConfigMap the "
        "running pod never re-read is a silent no-op."
    )


def test_the_register_endpoint_is_gone(info_payload: dict, base_url: str) -> None:
    """404 from the door itself, not merely a `false` in an advisory payload.

    A 400 here means the route is still registered and only rejected the empty body,
    which is registration being OPEN. `follow_redirects=False` so a redirect is never
    mistaken for a refusal.
    """
    response = httpx.post(f"{base_url}{REGISTER_PATH}", json={}, timeout=15.0, follow_redirects=False)

    assert response.status_code == 404, (
        f"POST {REGISTER_PATH} returned {response.status_code}, expected 404.\n"
        "400 means the route is still registered and rejected only the empty payload: "
        "a real payload would create an account. The advertised "
        "`registration_enabled` flag is a claim about this endpoint; this is the "
        "endpoint."
    )
