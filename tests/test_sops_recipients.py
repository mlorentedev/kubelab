"""Only the operator's key decrypts the repository's secrets (SEC-022, #1852).

No workflow reads a SOPS key, and a key held by CI could decrypt every secret and,
through the Cloudflare token among them, lift a backup bucket's lock. Editing
`.sops.yaml` revokes nothing on its own, so the file metadata is checked as well:
key names and recipients are plaintext in a SOPS file, so this needs no decryption.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
SECRETS = sorted((REPO / "infra" / "config" / "secrets").glob("*.enc.yaml"))


def _declared() -> set[str]:
    rules = yaml.safe_load((REPO / ".sops.yaml").read_text(encoding="utf-8"))["creation_rules"]
    return {key for rule in rules for group in rule["key_groups"] for key in group["age"]}


def test_sops_yaml_declares_one_recipient() -> None:
    assert len(_declared()) == 1


def test_the_secret_files_were_found() -> None:
    assert SECRETS


@pytest.mark.parametrize("path", SECRETS, ids=lambda path: path.name)
def test_each_file_is_encrypted_to_the_declared_recipient_only(path: pathlib.Path) -> None:
    metadata = yaml.safe_load(path.read_text(encoding="utf-8"))["sops"]
    groups = metadata.get("key_groups") or [{"age": metadata["age"]}]
    recipients = {entry["recipient"] for group in groups for entry in group["age"]}
    assert recipients == _declared()
