"""SEC-032 (#2242): the OIDC signing key has one store, SOPS.

A gitignored `infra/config/secrets/{env}.oidc-jwks.pem` used to sit beside it,
written once by `toolkit secrets jwks` and reconciled by nothing. Measured on
msi: every env's pem held a different key from SOPS, and SOPS is what K8s
Authelia serves. These tests keep a second copy from coming back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from toolkit.features.secrets_manager import SECRET_CATALOG, SecretsManager

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infra/stacks/services/security/authelia/compose.base.yml"
TEMPLATE = ROOT / "infra/config/authelia/templates/configuration.yml.j2"
KEY_PATH = next(s.key_path for s in SECRET_CATALOG if s.key_path.endswith(".oidc_jwks_private_key"))
# The toolkit exports every SOPS value to Compose under its flattened name.
ENV_NAME = KEY_PATH.upper().replace(".", "_")


def _template_key_path() -> str:
    """The in-container path the Authelia template reads the key from."""
    paths = re.findall(r'secret "([^"]+oidc-jwks\.pem)"', TEMPLATE.read_text())
    assert len(paths) == 1, f"expected one key path in {TEMPLATE.name}, found {paths}"
    return paths[0]


class TestTheDevStackReadsSops:
    def test_no_host_file_is_mounted(self) -> None:
        volumes = yaml.safe_load(COMPOSE.read_text())["services"]["authelia"].get("volumes", [])
        assert not [v for v in volumes if "oidc-jwks" in str(v)], "the key must not come from a host file"

    def test_the_key_is_a_secret_sourced_from_the_sops_variable(self) -> None:
        compose = yaml.safe_load(COMPOSE.read_text())
        mounts = [m for m in compose["services"]["authelia"].get("secrets", []) if isinstance(m, dict)]
        target = _template_key_path()
        sources = [m["source"] for m in mounts if m.get("target") == target]
        assert sources, f"no secret is mounted at {target}, the path the template reads"
        assert compose["secrets"][sources[0]] == {"environment": ENV_NAME}


def test_generating_a_key_writes_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stored: dict[str, str] = {}

    class _Config:
        def update_secret_key(self, path: str, value: str) -> bool:
            stored[path] = value
            return True

    class _Credentials:
        def generate_jwks_rsa_key(self, _size: int) -> str:
            return "not-a-real-key"

    manager = SecretsManager(tmp_path)
    monkeypatch.setattr(manager, "_cm", lambda env: _Config())
    monkeypatch.setattr(manager, "_credentials_manager", lambda: _Credentials())

    assert manager.generate_jwks("dev") == "not-a-real-key"
    assert stored == {KEY_PATH: "not-a-real-key"}
    assert not [p for p in tmp_path.rglob("*") if p.is_file()], "SOPS is the only store"


def _text_files() -> list[Path]:
    files = [ROOT / "Makefile"]
    for top in ("toolkit", "infra"):
        files += [
            p
            for p in (ROOT / top).rglob("*")
            if p.is_file() and p.suffix in {".py", ".yml", ".yaml", ".j2", ".sh", ".mk"}
        ]
    return files


def test_nothing_reads_or_writes_a_host_copy() -> None:
    """Only the in-container path may name the file; anything else is a second store."""
    allowed = _template_key_path()
    offenders: list[str] = []
    for path in _text_files():
        text = path.read_text(errors="ignore")
        if "JWKS_FILE_TEMPLATE" in text:
            offenders.append(f"{path.relative_to(ROOT)}: JWKS_FILE_TEMPLATE")
        for match in re.finditer(r"\S*oidc-jwks\.pem", text):
            if match.group(0).strip("'\"") != allowed:
                offenders.append(f"{path.relative_to(ROOT)}: {match.group(0)}")
    assert not offenders, offenders
