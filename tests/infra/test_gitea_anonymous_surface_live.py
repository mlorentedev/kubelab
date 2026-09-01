"""Infrastructure: Gitea refuses its surface to anonymous callers, on the LIVE host.

SEC-GITEA-001 (#1389) AC1 asks for a refused anonymous request against the running
instance -- "demonstrated by curl output, not by reading the template". Two suites
already exist that look like they cover this, and neither does:

- `tests/test_gitea_anonymous_surface.py` asserts on the RENDERED TEMPLATE. It
  proves the setting is written down. It cannot prove the container was ever
  re-provisioned with it, and a merged template is not a deployed one.
- The prod e2e suite was 6/6 green on 2026-08-27. It probes `/api/healthz`, which
  is what `health_path` declares in common.yaml and which `REQUIRE_SIGNIN_VIEW`
  EXEMPTS by design. Its greenness is compatible with the entire rest of the
  surface being world-readable.

So this file asserts the remaining axis, and it is the axis that matters: what an
anonymous caller on the internet actually gets. `gitea.kubelab.live` has a public
Cloudflare A record and its IngressRoute carries no network restriction.

The four paths below are exactly the ones measured at 200 on 2026-08-24, before
the fix. `/explore` is deliberately NOT among them -- it answered 303 even then,
so asserting on it would pass without the hardening and prove nothing.

Why an infra test and not a unit one: the failure this guards against is a
container running an older environment than the template in git. No amount of
manifest inspection reaches it. Only the running instance knows.
"""

from __future__ import annotations

import os
from urllib.parse import urljoin, urlsplit

import httpx
import pytest
import yaml

pytestmark = pytest.mark.infra

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_COMMON_YAML = os.path.abspath(os.path.join(_REPO_ROOT, "infra/config/values/common.yaml"))

#: Measured anonymously against the live host on 2026-08-24, BEFORE the fix:
#:
#:     /explore/repos    200
#:     /explore/users    200      <- anonymous account enumeration
#:     /api/swagger      200
#:     /api/v1/version   200      {"version":"1.25.5"}
#:
#: `/api/swagger` needed its own setting (`ENABLE_SWAGGER: false`) because it is a
#: static asset rather than a gated API route -- `REQUIRE_SIGNIN_VIEW` alone left
#: it at 200 while `/api/v1/version` had already dropped to 403. Keep both.
CLOSED_PATHS = (
    "/explore/repos",
    "/explore/users",
    "/api/swagger",
    "/api/v1/version",
)

#: A refusal, or a redirect that lands on the login page. NOT a bare "!= 200":
#: with `REQUIRE_SIGNIN_VIEW` Gitea answers many paths with a 3xx to
#: `/user/login`, which is a refusal, while an unreachable backend answers 502
#: through Traefik's error-pages -- also "!= 200", and NOT a refusal. The two are
#: told apart here rather than lumped together.
REFUSED_STATUSES = frozenset({401, 403, 404})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _gitea() -> dict:
    """The Gitea service block, from the SSOT. Never a literal -- CLAUDE.md's rule.

    A test carrying its own copy of the domain keeps passing after the domain
    changes, which makes it a slower way of not testing.
    """
    with open(_COMMON_YAML, encoding="utf-8") as handle:
        common = yaml.safe_load(handle)
    return common["apps"]["services"]["core"]["gitea"]


@pytest.fixture(scope="module")
def base_url() -> str:
    return f"https://{_gitea()['domain']}"


@pytest.fixture(scope="module")
def forge_is_up(base_url: str) -> None:
    """Guard the guard: skip when the backend is down, never pass vacuously.

    The Beelink is on-demand (ADR-028), so "the forge is not answering" is a
    normal state and not a finding. But it is also indistinguishable from a
    hardened forge if the assertion is written as `status != 200`: Traefik
    answers 502 through error-pages for an unreachable backend, and every
    assertion below would go green against a Gitea that is not running at all.

    `health_path` is the one endpoint exempt from `REQUIRE_SIGNIN_VIEW`, which is
    what makes it usable as a liveness probe for a suite about refusals.
    """
    health = _gitea()["health_path"]
    try:
        response = httpx.get(f"{base_url}{health}", timeout=10.0)
    except httpx.HTTPError as exc:
        pytest.skip(f"Gitea unreachable at {base_url}{health} ({exc}) — Beelink is on-demand")
    if response.status_code != 200:
        pytest.skip(
            f"Gitea not healthy: {health} returned {response.status_code}, expected 200. "
            "Refusal assertions would pass vacuously against a forge that is down."
        )


@pytest.mark.parametrize("path", CLOSED_PATHS)
def test_an_anonymous_caller_is_refused(forge_is_up: None, base_url: str, path: str) -> None:
    """No anonymous 200 on any path that leaked before the fix.

    `follow_redirects=False` is load-bearing: following a 303 to `/user/login`
    would return 200 for the login page, and the assertion would fail against a
    correctly hardened instance.
    """
    response = httpx.get(f"{base_url}{path}", timeout=15.0, follow_redirects=False)

    if response.status_code in REDIRECT_STATUSES:
        location = response.headers.get("location", "")
        # Resolved and compared by origin AND exact path, not by substring. A
        # substring check accepts `https://attacker.example/user/login`,
        # `/user/login-evil` and `/foo/user/login` -- none of which is Gitea's
        # login page, all of which would let an anonymous-access regression pass.
        # `urljoin` first because Gitea sends a relative Location.
        target = urlsplit(urljoin(f"{base_url}{path}", location))
        expected = urlsplit(base_url)
        # The query is deliberately excluded from the comparison: Gitea appends
        # `?redirect_to=<path>`, so demanding an exact URL would fail against the
        # real forge for a reason that has nothing to do with the refusal.
        assert (target.scheme, target.netloc, target.path) == (expected.scheme, expected.netloc, "/user/login"), (
            f"anonymous GET {path} redirected to {location!r}, which is not Gitea's login page. "
            "A redirect somewhere else is not a refusal."
        )
        return

    assert response.status_code in REFUSED_STATUSES, (
        f"anonymous GET {path} returned {response.status_code}, expected one of "
        f"{sorted(REFUSED_STATUSES)} or a redirect to /user/login.\n"
        "This is SEC-GITEA-001 (#1389): the surface is open to the internet. "
        "The template in git may well be correct — check whether the running "
        "container was ever re-provisioned with it (`make provision NODE=bee ENV=prod`; "
        "the playbook is `provision-bee.yml`, not `provision-beelink`)."
    )


def test_the_version_string_does_not_leak(forge_is_up: None, base_url: str) -> None:
    """Assert on the body, not only on the status.

    The status is the mechanism; the version string is the thing that leaks. A
    future change that returns 200 with an empty body would be caught by neither
    assertion alone, and asserting on content is what survives Gitea changing
    which status it uses to refuse.
    """
    response = httpx.get(f"{base_url}/api/v1/version", timeout=15.0, follow_redirects=False)
    declared = str(_gitea()["image"]).rsplit(":", 1)[-1]

    assert declared not in response.text, (
        f"anonymous GET /api/v1/version leaked the version {declared!r} in its body "
        f"(status {response.status_code}). Publishing the exact patch version of an "
        "internet-facing forge hands an attacker the CVE list for free."
    )
