"""Regression test for the vikunja-secrets R2 key wiring (TOOL-050 follow-up).

Found live: the ConfigMap/Secret used `VIKUNJA_FILES_S3_ACCESSKEYID` and
`VIKUNJA_FILES_S3_SECRETACCESSKEY` -- neither is a real Vikunja config key.
Its actual schema is `files.s3.accesskey` / `files.s3.secretkey`
(`VIKUNJA_FILES_S3_ACCESSKEY` / `VIKUNJA_FILES_S3_SECRETKEY` as env vars),
confirmed against pkg/config/config.go. Viper silently ignores unrecognized
keys, so the wrong names never errored -- they just never worked, from
IDP-035 onward (ADR-066 amendment, 2026-08-31).
"""

from __future__ import annotations

from toolkit.features.k8s_secrets import SECRET_DEFINITIONS, _apply_single_secret


def _vikunja_mapping():
    return next(m for m in SECRET_DEFINITIONS if m.name == "vikunja-secrets")


_REQUIRED_ENV = {
    "APPS_SERVICES_CORE_VIKUNJA_DB_PASSWORD": "not-a-real-value-fixture-db",
    "APPS_SERVICES_SECURITY_AUTHELIA_OIDC_CLIENT_SECRET_VIKUNJA": "not-a-real-value-fixture-oidc",
    "APPS_SERVICES_CORE_VIKUNJA_JWT_SECRET": "not-a-real-value-fixture-jwt",
}


class TestVikunjaR2Wiring:
    def test_r2_keys_resolve_from_the_actual_catalog_env_var_names(self, mocker) -> None:
        run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
        run.return_value = mocker.Mock(stdout="secret/vikunja-secrets configured", returncode=0)
        env_vars = {
            **_REQUIRED_ENV,
            "APPS_SERVICES_CORE_VIKUNJA_R2_ACCESS_KEY": "not-a-real-value-fixture-r2-access",
            "APPS_SERVICES_CORE_VIKUNJA_R2_SECRET_KEY": "not-a-real-value-fixture-r2-secret",
        }

        ok = _apply_single_secret(_vikunja_mapping(), env_vars, {}, dry_run=False, env="prod")

        assert ok is True
        manifest = run.call_args.kwargs["input"]
        assert "VIKUNJA_FILES_S3_ACCESSKEY" in manifest
        assert "VIKUNJA_FILES_S3_SECRETKEY" in manifest

    def test_r2_keys_stay_optional_when_absent(self, mocker) -> None:
        run = mocker.patch("toolkit.features.k8s_secrets.subprocess.run")
        run.return_value = mocker.Mock(stdout="secret/vikunja-secrets configured", returncode=0)

        ok = _apply_single_secret(_vikunja_mapping(), dict(_REQUIRED_ENV), {}, dry_run=False, env="prod")

        assert ok is True, "R2 keys are optional — their absence must not block the required keys"
        manifest = run.call_args.kwargs["input"]
        assert "VIKUNJA_FILES_S3_ACCESSKEY" not in manifest
        assert "VIKUNJA_FILES_S3_SECRETKEY" not in manifest
