"""Tests for SEC-SECRETS-001 (#831): harden K8s secret delivery.

Two structural weaknesses from the 2026-07-06 audit:

- **C5** — every secret value (incl. the RSA-4096 JWKS key) was passed as
  `kubectl create secret … --from-literal=KEY=VALUE` **argv**, readable via
  `/proc/<pid>/cmdline` for the duration of the call. The manifest is now
  rendered in-process and applied via `kubectl apply -f -` (stdin) — no value
  ever reaches argv.
- **C13** — `users_database.yml` / apprise `kubelab.yml` were hand-rendered with
  f-strings, so a value containing `"`, `:` or a newline produced invalid YAML
  (and Authelia then failed to parse its user DB, locking everyone out). Both are
  now built as dicts and `yaml.safe_dump`-ed.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

import yaml

from toolkit.features import k8s_secrets as ks
from toolkit.features.k8s_secrets import (
    SecretMapping,
    _apply_single_secret,
    _build_apprise_config,
    _build_users_database,
    _render_secret_manifest,
)


def _cm(merged: dict) -> MagicMock:
    cm = MagicMock()
    cm.get_merged_config.return_value = merged
    return cm


class TestNoSecretsInArgv:
    def test_secret_value_never_reaches_subprocess_argv(self, mocker) -> None:
        run = mocker.patch.object(
            ks.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="secret/x configured", stderr=""),
        )
        secret = "s3cr3t-RSA-VALUE-do-not-leak"
        mapping = SecretMapping(name="x", keys={"token": "TOKEN_ENV"})

        ok = _apply_single_secret(mapping, {"TOKEN_ENV": secret}, {}, dry_run=False)

        assert ok is True
        assert run.call_count == 1, "only `kubectl apply -f -` should run (no `create` subprocess)"
        cmd = run.call_args.args[0]
        assert cmd[-3:] == ["apply", "-f", "-"]
        assert not any(secret in str(part) for part in cmd), "secret must not appear in argv"
        # It rides in stdin, base64-encoded inside the Secret manifest.
        stdin = run.call_args.kwargs["input"]
        assert secret not in stdin, "raw secret must not appear even in stdin (base64-encoded)"
        assert base64.b64encode(secret.encode()).decode() in stdin

    def test_partial_render_still_fails_closed_without_subprocess(self, mocker) -> None:
        run = mocker.patch.object(ks.subprocess, "run")
        mapping = SecretMapping(name="x", keys={"a": "A_ENV", "b": "B_ENV"})

        ok = _apply_single_secret(mapping, {"A_ENV": "present"}, {}, dry_run=False)  # B missing

        assert ok is False, "TOOL-018 fail-closed must survive the refactor"
        run.assert_not_called()


class TestRenderSecretManifest:
    def test_base64_roundtrip_and_shape(self) -> None:
        out = _render_secret_manifest("x", "kube-system", {"a": "hello", "b": 'mul\nti:line"'})
        doc = yaml.safe_load(out)  # must be valid YAML

        assert doc["kind"] == "Secret"
        assert doc["type"] == "Opaque"
        assert doc["metadata"] == {"name": "x", "namespace": "kube-system"}
        assert base64.b64decode(doc["data"]["a"]).decode() == "hello"
        assert base64.b64decode(doc["data"]["b"]).decode() == 'mul\nti:line"'


class TestYamlBuildersEscape:
    def test_users_db_survives_hostile_displayname(self) -> None:
        merged = {
            "apps": {
                "services": {
                    "security": {
                        "authelia": {
                            "users": [
                                {"username": "bob", "displayname": 'B"ob: the\nbuilder', "groups": ["admins"]}
                            ],
                            "users_bob_password_hash": "$argon2id$v=19$m=65536,t=3,p=4$abc:def",
                        }
                    }
                },
                "auth": {"admin_username": ""},
            }
        }
        out = _build_users_database(_cm(merged))
        parsed = yaml.safe_load(out)  # f-string version would raise here

        assert parsed["users"]["bob"]["displayname"] == 'B"ob: the\nbuilder'
        assert parsed["users"]["bob"]["password"] == "$argon2id$v=19$m=65536,t=3,p=4$abc:def"
        assert parsed["users"]["bob"]["groups"] == ["admins"]

    def test_apprise_config_is_valid_yaml_with_tags(self) -> None:
        merged = {
            "apps": {
                "services": {
                    "automation": {
                        "apprise": {"telegram": {"bot_token": "123:ABC-def", "chat_page": "-1001", "chat_log": "-1002"}}
                    }
                }
            }
        }
        out = _build_apprise_config(_cm(merged))
        parsed = yaml.safe_load(out)

        assert parsed["version"] == 1
        tags = [next(iter(u.values()))["tag"] for u in parsed["urls"]]
        assert tags == ["page", "log"]
