"""Infrastructure: the SEC-004 rate limit is live on every route in the cluster.

`tests/test_rate_limit_coverage.py` proves the *manifests* carry `rate-limit`.
That is a claim about git, and git was not the thing that failed: on 2026-08-15
prod's `argo.kubelab.live` route ran without the middleware for hours while every
static test passed and `kubelab-prod` reported `Synced`, because that route's
manifest lives outside the Argo CD overlay and nothing had applied it
(kubelab#970, `tests/test_orphan_manifests.py`).

So this suite asserts the other axis -- what the cluster actually runs. Run it
after any deploy that touches routing:

    make test-infra ENV=prod
    make test-infra ENV=staging

Expectations come from `common.yaml`, never from the manifest under test:
comparing a manifest to itself passes for any pair of values, which is how
`tls: {}` survived months in prod (docs/lessons.md, 2026-08-09).
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest
import yaml

pytestmark = pytest.mark.infra

_KUBECONFIG_PATTERN = "~/.kube/kubelab-{env}-config"
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_COMMON_YAML = os.path.abspath(os.path.join(_REPO_ROOT, "infra/config/values/common.yaml"))

#: The middleware every route must carry. Name is the contract between
#: `base/edge/rate-limit.yaml` and every `middlewares:` list referencing it.
MIDDLEWARE_NAME = "rate-limit"

#: Guard-the-guard floor. Prod rendered 18 route entries and staging 14 when
#: SEC-004 shipped; a cluster reporting fewer than this is either half-deployed
#: or being queried wrong, and the coverage assertion below would pass vacuously.
MIN_EXPECTED_ROUTES = 10


def _get_kubeconfig(env: str) -> str:
    env_specific = os.path.expanduser(_KUBECONFIG_PATTERN.format(env=env))
    if os.path.exists(env_specific):
        return env_specific
    if kubeconfig := os.environ.get("KUBECONFIG"):
        return kubeconfig
    return env_specific


def _kubectl(args: str, env: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    kubeconfig = _get_kubeconfig(env)
    return subprocess.run(
        f"kubectl --kubeconfig {kubeconfig} {args}",
        shell=True,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _expected_rate_limit() -> dict:
    """The SSOT values, read from common.yaml (not from the manifest)."""
    with open(_COMMON_YAML, encoding="utf-8") as handle:
        edge = yaml.safe_load(handle)["edge"]["traefik"]
    return {
        "average": edge["rate_limit_k3s_average"],
        "burst": edge["rate_limit_k3s_burst"],
        "period": edge["rate_limit_k3s_period"],
    }


@pytest.fixture(scope="module")
def require_kubeconfig(env: str) -> None:
    kubeconfig = _get_kubeconfig(env)
    if not os.path.exists(kubeconfig):
        pytest.skip(f"Kubeconfig not found: {kubeconfig}")
    result = _kubectl("cluster-info", env, timeout=10)
    if result.returncode != 0:
        pytest.skip(f"K3s cluster unreachable: {result.stderr.strip()}")


@pytest.fixture(scope="module")
def live_ingressroutes(require_kubeconfig: None, env: str) -> list[dict]:
    """Every IngressRoute in the cluster, all namespaces.

    All namespaces on purpose. SEC-004's acceptance criterion is "every K3s
    IngressRoute", and a route that appears in another namespace is exactly the
    case a `kubelab`-scoped query would miss. If a third-party chart ever adds
    one, this suite should fail loudly and force a decision -- exempt it
    deliberately, or cover it -- rather than let it be uncovered by default.
    """
    result = _kubectl("get ingressroute -A -o json", env, timeout=30)
    if result.returncode != 0:
        pytest.skip(f"Could not list IngressRoutes: {result.stderr.strip()}")
    return json.loads(result.stdout).get("items", [])


class TestRateLimitMiddlewareIsLive:
    def test_middleware_object_exists(self, require_kubeconfig: None, env: str) -> None:
        result = _kubectl(f"-n kubelab get middleware {MIDDLEWARE_NAME} -o json", env)
        assert result.returncode == 0, (
            f"Middleware/{MIDDLEWARE_NAME} missing from the {env} cluster. Every route "
            f"references it by name, so its absence makes those references dangle "
            f"(Traefik drops the route). kubectl said: {result.stderr.strip()}"
        )

    def test_live_values_match_ssot(self, require_kubeconfig: None, env: str) -> None:
        """Catches a hand-edited live object, and a deploy that never landed."""
        result = _kubectl(f"-n kubelab get middleware {MIDDLEWARE_NAME} -o json", env)
        if result.returncode != 0:
            pytest.fail(f"Middleware/{MIDDLEWARE_NAME} not readable: {result.stderr.strip()}")

        live = json.loads(result.stdout)["spec"]["rateLimit"]
        expected = _expected_rate_limit()
        actual = {key: live.get(key) for key in expected}
        assert actual == expected, (
            f"Live rate-limit in {env} has drifted from common.yaml's "
            f"edge.traefik.rate_limit_k3s_*: live={actual} ssot={expected}"
        )

    def test_source_criterion_is_request_host(self, require_kubeconfig: None, env: str) -> None:
        """Per-router buckets depend on this, and it is not Traefik's default.

        Falling back to default client-IP keying would look global only by
        accident of klipper-lb masquerading every client (kubelab#1067) -- and
        would silently change behavior the day #1067 is fixed.
        """
        result = _kubectl(f"-n kubelab get middleware {MIDDLEWARE_NAME} -o json", env)
        if result.returncode != 0:
            pytest.fail(f"Middleware/{MIDDLEWARE_NAME} not readable: {result.stderr.strip()}")
        live = json.loads(result.stdout)["spec"]["rateLimit"]
        assert live.get("sourceCriterion", {}).get("requestHost") is True, (
            f"sourceCriterion.requestHost must be true in {env}; got {live.get('sourceCriterion')}"
        )


class TestEveryLiveRouteIsRateLimited:
    def test_enough_routes_found(self, live_ingressroutes: list[dict]) -> None:
        """Guard the guard: a near-empty list makes the coverage test vacuous."""
        total = sum(len(item["spec"].get("routes", [])) for item in live_ingressroutes)
        assert total >= MIN_EXPECTED_ROUTES, (
            f"Found only {total} live routes (expected >={MIN_EXPECTED_ROUTES}). "
            "The cluster is half-deployed, or this query is wrong -- either way the "
            "coverage assertion below would pass without proving anything."
        )

    def test_every_route_references_rate_limit(self, live_ingressroutes: list[dict]) -> None:
        uncovered: list[str] = []
        for item in live_ingressroutes:
            namespace = item["metadata"]["namespace"]
            name = item["metadata"]["name"]
            for index, route in enumerate(item["spec"].get("routes", [])):
                names = {m.get("name") for m in route.get("middlewares", [])}
                if MIDDLEWARE_NAME not in names:
                    match = route.get("match", "<no match>")
                    uncovered.append(f"{namespace}/{name}[{index}] match={match} middlewares={sorted(names)}")

        assert not uncovered, (
            "Live routes without the rate-limit middleware:\n  "
            + "\n  ".join(uncovered)
            + "\n\nSEC-004 (kubelab#970) applies it blanket, with no per-route opt-out. "
            "If the manifest already carries it, the route was never re-applied -- check "
            "whether it is an out-of-band manifest (tests/test_orphan_manifests.py lists them)."
        )
