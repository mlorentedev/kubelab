"""SEC-GITEA-001 (#1389) — Gitea must not serve its surface to anonymous visitors.

`gitea.kubelab.live` has a public Cloudflare A record (`infra/terraform/dns/
services.json`) and its IngressRoute in `overlays/prod/gitea.yaml` carries
`secure-headers`, `rate-limit`, `crowdsec-bouncer` and `error-pages` — no network
restriction. The backend is the Beelink over the tailnet, so an on-demand homelab
node publishes its login surface to the internet whenever it is powered on.

`REQUIRE_SIGNIN_VIEW` defaults to `false` in Gitea, and it was unset. Measured
2026-08-24, before the fix, against the live host:

    /                200
    /explore         303
    /explore/repos   200
    /explore/users   200      <- anonymous account enumeration
    /api/swagger     200
    /api/v1/version  200      {"version":"1.25.5"}

**Nothing leaked, and that was not a control.** The forge was empty; the only
thing standing between an anonymous visitor and any repository marked public was
the absence of repositories. TOOL-035 (#1076) exists to end that, which is why
this had to land first — the cheap moment is strictly before the first push.

Asserted against the RENDERED template rather than the file text, because a
value that appears only in a comment is exactly the false green this repo keeps
hitting (see `_directive`'s docstring in test_beelink_compose_unit.py, and
lesson-021's addendum where a comment and its value agreed and both were wrong).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import ChainableUndefined, Environment, FileSystemLoader

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/beelink_services"

#: Values Ansible supplies from outside the role. The rest render as empty via
#: ChainableUndefined, and that is SAFE HERE for a reason worth stating rather
#: than assuming: every assertion below is on a LITERAL in the template
#: (`"true"`, `"false"`), never on an interpolated variable. An unfilled variable
#: can therefore make the render fail or produce an empty value — it cannot
#: manufacture a pass. StrictUndefined would instead couple this security guard
#: to the full variable surface of an unrelated three-service role, so any new
#: variable anywhere in the stack would break it for no security reason.
_EXTERNAL = dict(
    ansible_managed="Ansible managed",
    tailscale_ip="100.64.0.3",
    gitea_image="gitea/gitea:1.25.5",
    gitea_domain="gitea.kubelab.live",
)


def _vars() -> dict:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text()) or {}
    return {**defaults, **_EXTERNAL}


def _gitea_environment() -> dict[str, str]:
    """The `environment:` block Gitea actually receives, parsed from the render."""
    env = Environment(
        loader=FileSystemLoader(str(ROLE / "templates")),
        undefined=ChainableUndefined,
    )
    rendered = env.get_template("compose.yml.j2").render(**_vars())
    compose = yaml.safe_load(rendered)
    assert compose and "gitea" in compose.get("services", {}), (
        "the compose template no longer renders a `gitea` service — this guard is "
        "asserting on nothing; fix the render before trusting the results below"
    )
    return {str(k): str(v) for k, v in (compose["services"]["gitea"].get("environment") or {}).items()}


def test_anonymous_visitors_cannot_browse():
    """The one setting that closes explore, the API and Swagger in a single change.

    Gitea's default is `false`. It must be declared, not assumed — the whole
    reason this ticket exists is that an unset value silently took the permissive
    branch on an internet-facing host.
    """
    value = _gitea_environment().get("GITEA__service__REQUIRE_SIGNIN_VIEW")
    assert value == "true", (
        f"GITEA__service__REQUIRE_SIGNIN_VIEW is {value!r}. Unset or false means /explore, "
        "/explore/users, /api/swagger and /api/v1/version answer anonymous requests on a "
        "publicly-resolvable host."
    )


def test_registration_stays_closed():
    """Guarded here too, so one file answers 'what can an anonymous visitor do'.

    AUTH-004's C4 demonstrated both signup surfaces refusing at the handler with
    403, and that demonstration rests on this flag. C4's own task text says it
    must be re-demonstrated if the flag changes — so the flag should not be able
    to change unnoticed.
    """
    env = _gitea_environment()
    assert env.get("GITEA__service__DISABLE_REGISTRATION") == "true"
    assert env.get("GITEA__openid__ENABLE_OPENID_SIGNUP") == "false", (
        "OpenID signup would re-open self-registration through a different door than "
        "DISABLE_REGISTRATION closes"
    )


def test_the_setting_is_a_value_and_not_only_a_comment():
    """The anti-false-green, and it has earned its place in this repository.

    The template explains this change at length and the explanation names the
    variable. A test grepping the file text would pass on the prose alone. This
    asserts on the parsed `environment:` mapping, so only a real value counts.

    lesson-021's addendum is the sharper version of the same hazard: there, a
    comment and the value beneath it AGREED, and both were wrong about the
    client. Prose is never the evidence.
    """
    raw = (ROLE / "templates/compose.yml.j2").read_text()
    assert "REQUIRE_SIGNIN_VIEW" in raw
    mentions = raw.count("REQUIRE_SIGNIN_VIEW")
    assert "GITEA__service__REQUIRE_SIGNIN_VIEW" in _gitea_environment(), (
        f"REQUIRE_SIGNIN_VIEW appears {mentions}x in the template but not in the rendered "
        "environment — it is prose, not configuration."
    )


def test_swagger_is_disabled():
    """REQUIRE_SIGNIN_VIEW does not cover the Swagger UI. Measured, not assumed.

    After the signin requirement landed, `/api/swagger` still answered **200**
    anonymously while `/api/v1/version` had dropped to 403 and `/explore/users`
    to 303. The page is served as a static asset rather than through the gated
    API router, so it needs its own switch.

    This was filed as the optional third step of #1389 and promoted to required
    by that measurement — which is the argument for checking the surface after
    the fix instead of reasoning about what the flag ought to cover.
    """
    value = _gitea_environment().get("GITEA__api__ENABLE_SWAGGER")
    assert value == "false", (
        f"GITEA__api__ENABLE_SWAGGER is {value!r}. REQUIRE_SIGNIN_VIEW leaves /api/swagger "
        "reachable, so the API documentation stays published to anonymous visitors."
    )


def test_the_healthcheck_does_not_use_an_endpoint_the_hardening_closes():
    """The probe must read `health_path` from the SSOT, not name a path itself.

    This is the defect that turned the hardening into an outage. `health_path:
    /api/healthz` had been declared in `common.yaml` since the move to the
    Beelink and was read by **nothing**; the compose healthcheck hardcoded
    `/api/v1/version`. The divergence was invisible while both endpoints
    answered anonymously — and the container went unhealthy the moment
    REQUIRE_SIGNIN_VIEW closed the API, because the probe had been
    authenticating by not needing to.

    Measured with signin required: `/api/healthz` 200, `/api/v1/version` 403.

    The general shape is the one this repo keeps meeting: a value declared in
    the SSOT with no reader is not a source of truth, it is a comment
    (lesson-380). Asserting the rendered probe carries the declared path is what
    makes it one.
    """
    import re

    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), undefined=ChainableUndefined)
    rendered = env.get_template("compose.yml.j2").render(**{**_vars(), "gitea_health_path": "/api/healthz"})
    compose = yaml.safe_load(rendered)
    test_cmd = " ".join(compose["services"]["gitea"]["healthcheck"]["test"])

    assert "/api/healthz" in test_cmd, (
        f"the gitea healthcheck is {test_cmd!r}; it must use the SSOT's health_path"
    )
    assert "/api/v1/" not in test_cmd, (
        f"the gitea healthcheck is {test_cmd!r}, which REQUIRE_SIGNIN_VIEW closes — "
        "the container would report unhealthy forever"
    )
    raw = (ROLE / "templates/compose.yml.j2").read_text()
    assert re.search(r"test:.*gitea_health_path", raw), (
        "the healthcheck must interpolate gitea_health_path rather than repeat a literal path — "
        "a second copy of the value is what diverged in the first place"
    )


def test_no_live_copy_of_the_health_path_survives():
    """Five literal copies existed, and the hardening broke all five at once.

    `health_path: /api/healthz` was declared in `common.yaml` when Gitea moved to
    the Beelink, and read by nothing. Meanwhile `/api/v1/version` was written out
    by hand in five places: the compose healthcheck, two probes in
    `gitea-bootstrap.sh`, the "Verify Gitea answers on its Tailscale address"
    task, and the `Wait for gitea to answer after restart` handler — plus a sixth
    in the e2e expectations.

    While both endpoints answered anonymously the divergence was free. Closing
    the API turned every one of them into a failure in the same run: the
    container went unhealthy, the verify task got 403, and the handler that
    lesson-381 exists to make fire would have failed once it did.

    The declaration was not a source of truth, because nothing read it — the
    shape lesson-380 describes. This asserts the readers exist.
    """
    role_files = [
        ROLE / "templates/compose.yml.j2",
        ROLE / "tasks/main.yml",
        ROLE / "handlers/main.yml",
        ROLE / "files/gitea-bootstrap.sh",
    ]
    offenders = []
    for path in role_files:
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue  # prose may cite the old path; only live code counts
            if "/api/v1/version" in line:
                offenders.append(f"{path.relative_to(REPO)}:{lineno}")

    assert not offenders, (
        f"these lines still probe /api/v1/version, which REQUIRE_SIGNIN_VIEW refuses with "
        f"403 to an anonymous caller: {offenders}. Read the path from the SSOT — "
        "`gitea_health_path` in Ansible, `$GITEA_HEALTH_PATH` in the bootstrap script."
    )
