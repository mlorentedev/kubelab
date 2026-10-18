"""The two Vikunja automation tokens are catalogued as what they are.

Vikunja mints an API token with a mandatory expiry, so neither token can be
`Expiry.NEVER`. They cannot be `Expiry.PROVIDER` either: that class means "the
issuer can be asked", and an API token is refused on `GET /tokens` (401, measured
on prod 2026-10-18), so no checker can read its expiry. `DECLARED` is the honest
class: the date the operator chose is recorded per env in `values/<env>.yaml`.
"""

import re

import pytest

from toolkit.features.secret_expiry import Expiry, resolve_expiry
from toolkit.features.secrets_manager import SECRET_CATALOG, SecretKind

N8N_KEY = "apps.services.automation.n8n.vikunja_api_token"
RECONCILER_KEY = "apps.services.core.vikunja.reconciler_api_token"


def _spec(key_path: str):
    matches = [s for s in SECRET_CATALOG if s.key_path == key_path]
    assert len(matches) == 1, f"{key_path} must be catalogued exactly once, found {len(matches)}"
    return matches[0]


@pytest.mark.parametrize("key_path", [N8N_KEY, RECONCILER_KEY])
def test_a_vikunja_token_is_external_and_shaped_like_one(key_path):
    spec = _spec(key_path)
    assert spec.kind is SecretKind.EXTERNAL
    assert spec.envs == ("staging", "prod")
    assert spec.value_pattern is not None
    assert re.fullmatch(spec.value_pattern, "tk_" + "0" * 40)
    assert not re.fullmatch(spec.value_pattern, "x" * 86)


@pytest.mark.parametrize("key_path", [N8N_KEY, RECONCILER_KEY])
def test_a_vikunja_token_is_not_classed_as_immortal_or_askable(key_path):
    assert resolve_expiry(_spec(key_path)) is Expiry.DECLARED


@pytest.mark.parametrize("key_path", [N8N_KEY, RECONCILER_KEY])
def test_the_rotate_note_says_who_mints_it_and_where_the_expiry_is_kept(key_path):
    note = _spec(key_path).rotate_note
    assert "operator" in note
    assert "secret_expiry.declared" in note


def test_the_reconciler_token_is_read_by_the_sync_client():
    from toolkit.features.vikunja_client import TOKEN_SECRET_KEY

    assert TOKEN_SECRET_KEY == RECONCILER_KEY


class TestDeclaredExpiries:
    def _cfg(self, **by_env):
        return lambda env: {"secret_expiry": {"declared": by_env.get(env, {})}}

    def test_an_env_with_no_recorded_date_is_a_finding_not_a_skip(self):
        from toolkit.features.secret_expiry import declared_expiries

        found = declared_expiries([_spec(N8N_KEY)], self._cfg())
        assert [(f.key_path, f.env, f.expires_on) for f in found] == [
            (N8N_KEY, "staging", None),
            (N8N_KEY, "prod", None),
        ]

    def test_a_recorded_date_is_read_per_env(self):
        from datetime import date

        from toolkit.features.secret_expiry import declared_expiries

        cfg = self._cfg(prod={N8N_KEY: "2027-01-16"}, staging={N8N_KEY: date(2026, 12, 1)})
        by_env = {f.env: f.expires_on for f in declared_expiries([_spec(N8N_KEY)], cfg)}
        assert by_env == {"staging": date(2026, 12, 1), "prod": date(2027, 1, 16)}

    def test_a_malformed_date_raises_naming_the_key(self):
        from toolkit.features.secret_expiry import declared_expiries

        with pytest.raises(ValueError, match="vikunja_api_token"):
            declared_expiries([_spec(N8N_KEY)], self._cfg(prod={N8N_KEY: "next spring"}))

    def test_only_declared_secrets_are_listed(self):
        from toolkit.features.secret_expiry import declared_expiries

        keys = {f.key_path for f in declared_expiries(SECRET_CATALOG, self._cfg())}
        assert keys == {N8N_KEY, RECONCILER_KEY}

    def test_days_left_counts_from_today(self):
        from datetime import date, timedelta

        from toolkit.features.secret_expiry import DeclaredExpiry

        assert DeclaredExpiry("k", "prod", date.today() + timedelta(days=10)).days_left == 10
        assert DeclaredExpiry("k", "prod", None).days_left is None


class TestTheReportNamesWhatIsMissing:
    def test_a_missing_date_is_warned_and_returned(self, monkeypatch):
        from unittest.mock import MagicMock

        import toolkit.cli.secrets as cli
        import toolkit.features.configuration as configuration

        monkeypatch.setattr(
            configuration,
            "ConfigurationManager",
            lambda env, root: MagicMock(get_merged_config=lambda: {}),
        )
        warn = MagicMock()
        monkeypatch.setattr(cli.logger, "warning", warn)
        missing, expiring = cli._declared_expiry_lines(90)
        assert len(missing) == 4 and expiring == []
        assert all("no expiry recorded" in c.args[0] for c in warn.call_args_list)

    def test_a_near_date_is_expiring(self, monkeypatch):
        from datetime import date, timedelta
        from unittest.mock import MagicMock

        import toolkit.cli.secrets as cli
        import toolkit.features.configuration as configuration

        soon = (date.today() + timedelta(days=5)).isoformat()
        cfg = {"secret_expiry": {"declared": {N8N_KEY: soon, RECONCILER_KEY: soon}}}
        monkeypatch.setattr(
            configuration, "ConfigurationManager", lambda env, root: MagicMock(get_merged_config=lambda: cfg)
        )
        monkeypatch.setattr(cli.logger, "error", MagicMock())
        missing, expiring = cli._declared_expiry_lines(90)
        assert missing == [] and len(expiring) == 4
