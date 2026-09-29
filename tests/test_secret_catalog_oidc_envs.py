"""The catalog audits an OIDC client's secrets in exactly the envs that register it.

`SecretSpec.envs` says which environments must hold a secret. For an OIDC
client that answer is already declared once, in `oidc_clients[].envs` in
`common.yaml`: Authelia registers the client there and nowhere else. The
catalog restated it by hand and drifted. Measured 2026-09-27: `secrets-audit
ENV=dev` reported 40/45, and three of the five "missing" keys were the Gitea
digest and the Vikunja pair, for clients the SSOT registers only in prod and in
staging+prod. An audit that is never green in one env stops being read in all
of them.

The digest is found by `digest_key`, the plaintext by the digest's
`derived_from`, so the rule holds for a client whose plaintext lives with its
consumer (Gitea) as well as for one whose plaintext lives with Authelia. A
client can also keep a second copy of its secret on the consumer side (Vikunja
reads `apps.services.core.vikunja.oidc_client_secret`): every OIDC client
secret the consumer service is listed on is held to the same envs.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from toolkit.features.oidc_clients import declared_clients, digest_key, load_values
from toolkit.features.secrets_manager import SECRET_CATALOG, SecretKind

REPO = pathlib.Path(__file__).resolve().parent.parent
_BY_PATH = {spec.key_path: spec for spec in SECRET_CATALOG}
_CLIENTS = declared_clients(load_values("staging"))


def test_the_sample_is_every_client_in_the_file() -> None:
    """The parametrized set is measured against common.yaml itself, not a floor.

    A loader change that drops a client would otherwise shrink the guard and
    still report green over fewer clients than the docstring promises.
    """
    raw = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
    in_file = {c["client_id"] for c in raw["apps"]["services"]["security"]["authelia"]["oidc_clients"]}
    assert in_file, "common.yaml declares no OIDC clients; the path moved"
    assert {c["client_id"] for c in _CLIENTS} == in_file


def test_no_env_overlay_declares_clients() -> None:
    """The sample reads common.yaml, so a client declared in an overlay would escape it.

    Overlays replace lists when they deep-merge, so a client added in
    `prod.yaml` would be parametrized nowhere and its catalog envs would drift
    unchecked. `envs` on each client is how one env differs from another.
    """
    for values in sorted((REPO / "infra/config/values").glob("*.yaml")):
        if values.name == "common.yaml":
            continue
        overlay = yaml.safe_load(values.read_text(encoding="utf-8")) or {}
        authelia = overlay.get("apps", {}).get("services", {}).get("security", {}).get("authelia", {})
        assert "oidc_clients" not in authelia, (
            f"{values.name} declares oidc_clients; declare them once in common.yaml with envs="
        )


@pytest.mark.parametrize("client", _CLIENTS, ids=lambda c: c["client_id"])
def test_digest_and_plaintext_are_audited_where_the_client_is_registered(client: dict) -> None:
    digest = _BY_PATH.get(digest_key(client["client_id"]))
    assert digest is not None, f"{digest_key(client['client_id'])} is not in SECRET_CATALOG"
    assert digest.derived_from, f"{digest.key_path} names no plaintext in derived_from"
    plaintext = _BY_PATH.get(digest.derived_from)
    assert plaintext is not None, f"{digest.derived_from} is not in SECRET_CATALOG"

    consumer = client["client_id"].removesuffix("-oidc")
    copies = [
        spec
        for spec in SECRET_CATALOG
        if spec.kind is SecretKind.OIDC_CLIENT_SECRET and consumer in spec.services and spec is not plaintext
    ]

    declared = set(client["envs"])
    for spec in (digest, plaintext, *copies):
        assert set(spec.envs) == declared, (
            f"{spec.key_path} is audited in {sorted(spec.envs)}, but oidc_clients registers "
            f"{client['client_id']} in {sorted(declared)}. Set envs= to match the SSOT."
        )
