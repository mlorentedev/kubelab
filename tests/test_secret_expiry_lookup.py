"""A provider-issued credential stored per environment must still be checked.

Both expiry reports resolved values from `ConfigurationManager("common")` alone,
so every PROVIDER secret living in `<env>.enc.yaml` was invisible to them. The two
callers failed differently and both failures were wrong:

  `secrets audit`         skipped it with no output at all
  `secrets check-expiry`  printed "declared PROVIDER but absent from SOPS"

Measured 2026-08-28 on `apps.services.core.gitea.github_migration_token`
(TOOL-035, #1076), which lives in `prod.enc.yaml` beside `bot_token`. The same
credential authenticated against GitHub and reported an expiry of 2026-10-27 in
the same session, so "absent from SOPS" was a false negative on a credential
control -- the shape `secret_expiry`'s docstring exists to prevent, since a key
nobody is warned about is indistinguishable from one that cannot expire.

Searching every file rather than threading one env through is deliberate:
`SecretSpec.envs` is the AUDIT dimension, not the storage location (ANSIBLE-033),
so the catalog cannot be asked which file holds a value. It also keeps
`check-expiry` -- which takes no `--env` -- correct by construction.
"""

from __future__ import annotations

from toolkit.cli.secrets import dig_across
from toolkit.features.secret_expiry import Expiry, resolve_expiry
from toolkit.features.secrets_manager import SECRET_CATALOG

COMMON = {"cloudflare": {"api_token": "in-common"}}
PROD = {"apps": {"services": {"core": {"gitea": {"github_migration_token": "in-prod"}}}}}


def test_a_value_in_common_is_found():
    assert dig_across([COMMON, PROD], "cloudflare.api_token") == "in-common"


def test_a_value_in_a_per_env_file_is_found():
    """The regression. Before the fix this returned "" and the caller said "absent"."""
    assert dig_across([COMMON, PROD], "apps.services.core.gitea.github_migration_token") == "in-prod"


def test_common_wins_when_a_key_exists_in_both():
    """Deterministic precedence, so a shadowed value cannot flip between runs."""
    shadowed = {"cloudflare": {"api_token": "in-prod"}}
    assert dig_across([COMMON, shadowed], "cloudflare.api_token") == "in-common"


def test_a_missing_key_is_empty_not_an_error():
    """Callers distinguish "" from a value; raising here would break the report."""
    assert dig_across([COMMON, PROD], "nothing.here.at.all") == ""


def test_an_empty_string_counts_as_absent():
    """A placeholder is not a credential: an empty value must not shadow a real one."""
    assert dig_across([{"a": {"b": ""}}, {"a": {"b": "real"}}], "a.b") == "real"


def test_a_non_dict_midway_does_not_raise():
    """`a.b.c` where `a.b` is a string: walking into it must fail closed, not crash."""
    assert dig_across([{"a": {"b": "scalar"}}], "a.b.c") == ""


def test_every_provider_secret_has_a_checker():
    """A PROVIDER secret with no checker is a gap, and the audit path skips it silently.

    `secret_expiry.PROVIDER_CHECKS`'s own comment says such a secret should be
    "a gap the report names rather than skips" — but `_report_expiry` does
    `if check is None ... continue`. Until that is reconciled, this test is what
    names it: declaring PROVIDER and wiring no checker means the credential is
    classified as expirable and then never checked, which reads exactly like a
    credential that cannot expire.
    """
    from toolkit.features.secret_expiry import PROVIDER_CHECKS

    # Headscale keys are asked of the server directly rather than through the
    # catalog, so they legitimately have no key_path entry.
    handled_elsewhere = {"gcp.headscale_api_key", "aws.headscale_api_key"}

    unchecked = [
        s.key_path
        for s in SECRET_CATALOG
        if resolve_expiry(s) is Expiry.PROVIDER
        and s.key_path not in PROVIDER_CHECKS
        and s.key_path not in handled_elsewhere
    ]
    assert not unchecked, (
        f"declared PROVIDER with no expiry checker: {unchecked}. Either wire one into "
        "PROVIDER_CHECKS or reclassify — a secret marked expirable that nothing asks "
        "about is reported as neither expiring nor expired."
    )
