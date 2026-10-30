"""The ACME DNS-01 token reaches DNS on its zones and nothing more (#2459).

The token's scope lives in the Cloudflare dashboard, so `make acme-token-scope`
asks Cloudflare. These tests pin how its answers are read, with a fake API: a
200 on zone settings must fail, and so must a zone the token cannot find, since
Traefik looks the zone up by name before it writes a challenge record.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features.acme_token_scope import ScopeUncheckableError, probe_acme_token

REPO = Path(__file__).resolve().parent.parent
ZONE_ID = "z1"


def _api(**overrides: tuple[int, dict[str, Any]]):
    """A Cloudflare that answers like a DNS:Edit-only token, unless overridden."""
    answers = {
        "/user/tokens/verify": (200, {"result": {"status": "active"}}),
        "/zones?name=kubelab.live": (200, {"result": [{"id": ZONE_ID}]}),
        f"/zones/{ZONE_ID}/dns_records?per_page=1": (200, {"result": []}),
        f"/zones/{ZONE_ID}/settings": (403, {}),
    }
    answers.update({k.replace("__", "/"): v for k, v in overrides.items()})

    def get(path: str, token: str) -> tuple[int, dict[str, Any]]:
        assert token == "t"
        return answers[path]

    return get


def _key(path: str) -> str:
    return path.replace("/", "__")


def test_a_dns_only_token_passes_every_probe() -> None:
    probes = probe_acme_token("t", ["kubelab.live"], get=_api())
    assert [p.action for p in probes] == ["find the zone by name", "read DNS records", "read zone settings"]
    assert all(p.ok for p in probes)


def test_a_token_that_can_read_zone_settings_fails() -> None:
    probes = probe_acme_token("t", ["kubelab.live"], get=_api(**{_key(f"/zones/{ZONE_ID}/settings"): (200, {})}))
    assert [p.action for p in probes if not p.ok] == ["read zone settings"]


def test_a_zone_the_token_cannot_find_fails_and_is_not_probed_further() -> None:
    empty = {_key("/zones?name=kubelab.live"): (200, {"result": []})}
    probes = probe_acme_token("t", ["kubelab.live"], get=_api(**empty))
    assert [(p.action, p.ok) for p in probes] == [("find the zone by name", False)]


def test_a_refused_zone_lookup_keeps_its_own_status() -> None:
    probes = probe_acme_token("t", ["kubelab.live"], get=_api(**{_key("/zones?name=kubelab.live"): (403, {})}))
    assert probes[0].got == 403


def test_a_token_cloudflare_does_not_accept_cannot_be_checked() -> None:
    with pytest.raises(ScopeUncheckableError):
        probe_acme_token("t", ["kubelab.live"], get=_api(**{_key("/user/tokens/verify"): (401, {})}))


@pytest.mark.parametrize("code", [429, 503])
def test_a_rate_limit_or_server_error_cannot_check_rather_than_failing_scope(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    """A 429 or 5xx says nothing about scope, so it must not read as a wrong answer."""
    import urllib.error
    import urllib.request

    from toolkit.features.acme_token_scope import http_get

    def refuse(req: object, timeout: float) -> None:
        raise urllib.error.HTTPError("u", code, "x", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(ScopeUncheckableError):
        http_get("/zones/z1/settings", "t")


def test_a_403_is_an_answer_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error
    import urllib.request

    from toolkit.features.acme_token_scope import http_get

    def refuse(req: object, timeout: float) -> None:
        raise urllib.error.HTTPError("u", 403, "x", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    assert http_get("/zones/z1/settings", "t") == (403, {})


def test_the_probed_zones_are_the_issuing_apexes() -> None:
    """The CLI probes `edge.traefik.acme_domains[].main`; it must keep naming zones."""
    common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
    mains = [d["main"] for d in common["edge"]["traefik"]["acme_domains"]]
    assert "kubelab.live" in mains
