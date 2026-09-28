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
consumer (Gitea) as well as for one whose plaintext lives with Authelia.
"""

from __future__ import annotations

import pytest

from toolkit.features.oidc_clients import declared_clients, digest_key, load_values
from toolkit.features.secrets_manager import SECRET_CATALOG

_BY_PATH = {spec.key_path: spec for spec in SECRET_CATALOG}
_CLIENTS = declared_clients(load_values("staging"))


def test_the_ssot_declares_clients_at_all() -> None:
    assert len(_CLIENTS) >= 3, f"found {[c.get('client_id') for c in _CLIENTS]}; the lookup drifted"


@pytest.mark.parametrize("client", _CLIENTS, ids=lambda c: c["client_id"])
def test_digest_and_plaintext_are_audited_where_the_client_is_registered(client: dict) -> None:
    digest = _BY_PATH.get(digest_key(client["client_id"]))
    assert digest is not None, f"{digest_key(client['client_id'])} is not in SECRET_CATALOG"
    assert digest.derived_from, f"{digest.key_path} names no plaintext in derived_from"
    plaintext = _BY_PATH.get(digest.derived_from)
    assert plaintext is not None, f"{digest.derived_from} is not in SECRET_CATALOG"

    declared = set(client["envs"])
    for spec in (digest, plaintext):
        assert set(spec.envs) == declared, (
            f"{spec.key_path} is audited in {sorted(spec.envs)}, but oidc_clients registers "
            f"{client['client_id']} in {sorted(declared)}. Set envs= to match the SSOT."
        )
