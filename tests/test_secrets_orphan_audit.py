"""DEBT-011 (#833): the secrets audit only ever looked in one direction.

`SecretsManager.audit` iterates `SECRET_CATALOG` and asks whether each entry has
a value. Nothing asked the reverse — whether a value has an entry — so a secret
whose catalog entry was removed, or that was never registered, stayed in the
vault permanently and invisibly.

That is not hypothetical. #1451 removed `apps.services.data.minio.root_user`
from the catalog because a root account's *name* is configuration, not a
credential; the encrypted value stayed behind, is read by nothing, and
`make secrets-audit` reported a clean 35/35 the whole time. And it is not inert:
`credentials generate` rewrites whatever it seeds, so an orphan is a value
something may still overwrite while nothing consumes it.

`AuditResult.unexpected` had been declared since the dataclass was written and
was never populated, while `cli/secrets.py` told the operator in its own help
that the audit reports exactly this. The claim preceded the code by a long way.

Every test here is pure: a dict standing in for a decrypted vault, no SOPS, no
age key, no network.
"""

from __future__ import annotations

from toolkit.features.secrets_manager import SECRET_CATALOG, orphan_key_paths

#: A key path the catalog really owns, so the test cannot pass by owning nothing.
OWNED = SECRET_CATALOG[0].key_path


def _nest(path: str, value: str) -> dict:
    """Build the nested dict shape a decrypted vault has, from a dotted path."""
    parts = path.split(".")
    node: dict = {parts[-1]: value}
    for key in reversed(parts[:-1]):
        node = {key: node}
    return node


def _merge(*trees: dict) -> dict:
    out: dict = {}

    def deep(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                deep(dst[k], v)
            else:
                dst[k] = v

    for tree in trees:
        deep(out, tree)
    return out


class TestOrphanDetection:
    def test_a_key_with_no_catalog_entry_is_reported(self) -> None:
        """The #1451 case: the entry was removed, the value stayed."""
        vault = _nest("apps.services.data.minio.root_user", "irrelevant")
        assert orphan_key_paths(vault) == ["apps.services.data.minio.root_user"]

    def test_a_key_the_catalog_owns_is_not_reported(self) -> None:
        assert orphan_key_paths(_nest(OWNED, "irrelevant")) == []

    def test_owned_and_orphaned_keys_coexist(self) -> None:
        vault = _merge(_nest(OWNED, "x"), _nest("apps.services.data.minio.root_user", "y"))
        assert orphan_key_paths(vault) == ["apps.services.data.minio.root_user"]

    def test_sops_metadata_is_never_an_orphan(self) -> None:
        """SOPS writes this into every file; nobody declares it, and it is not a secret."""
        vault = _merge(_nest(OWNED, "x"), {"sops": {"age": [{"recipient": "age1..."}], "version": "3.8.1"}})
        assert orphan_key_paths(vault) == []

    def test_an_owned_subtree_is_not_descended_into(self) -> None:
        """A catalog entry naming a subtree owns it whole.

        Otherwise a structured secret — a key whose value is a mapping — would
        report every one of its own leaves as an orphan.
        """
        vault = _nest(OWNED, "")
        # replace the leaf with a mapping, as a structured secret would be
        node = vault
        parts = OWNED.split(".")
        for key in parts[:-1]:
            node = node[key]
        node[parts[-1]] = {"inner": "a", "other": "b"}
        assert orphan_key_paths(vault) == []


class TestEnvScopingIsDeliberatelyIgnored:
    def test_an_entry_registered_for_another_env_is_not_an_orphan(self) -> None:
        """`envs` is the audit dimension, not ownership (ANSIBLE-033).

        A key registered for prod only still has an owner when auditing
        staging. Treating "not expected here" as "nobody owns this" would
        recreate that failure mode from the other side — and would report a
        long list of false orphans on every non-prod audit.
        """
        prod_only = next((s for s in SECRET_CATALOG if s.envs == ("prod",)), None)
        if prod_only is None:  # pragma: no cover - the catalog always has one today
            return
        assert orphan_key_paths(_nest(prod_only.key_path, "x")) == []


class TestItCannotLeakValues:
    def test_no_value_appears_in_the_output(self) -> None:
        """The transcript is a durable artifact and nothing scans it.

        A function that walks a decrypted vault must be structurally incapable
        of emitting what it walked — key paths only — rather than merely
        careful about it.
        """
        secret = "s3cr3t-value-that-must-never-be-printed"
        vault = _merge(_nest("apps.services.data.minio.root_user", secret), _nest(OWNED, secret))
        rendered = " ".join(orphan_key_paths(vault))
        assert secret not in rendered
        assert rendered == "apps.services.data.minio.root_user"

    def test_the_return_type_carries_no_values_at_all(self) -> None:
        """Belt and braces: a list of str, and every element is a key path."""
        vault = _nest("some.unregistered.key", "value")
        result = orphan_key_paths(vault)
        assert all(isinstance(item, str) and item == "some.unregistered.key" for item in result)
