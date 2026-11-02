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
# A public key. Named so that a comparison against `.sops.yaml` alone cannot pass
# with this key restored in both places.
RETIRED_CI_RECIPIENT = "age1wpqxa7vqkr6watypd6zlw7kspz506kq2kvluxnluhz72mgtaga3qlg84cv"


def _declared() -> set[str]:
    rules = yaml.safe_load((REPO / ".sops.yaml").read_text(encoding="utf-8"))["creation_rules"]
    return {key for rule in rules for group in rule["key_groups"] for key in group["age"]}


def test_sops_yaml_declares_one_recipient() -> None:
    declared = _declared()
    assert len(declared) == 1
    assert RETIRED_CI_RECIPIENT not in declared


def test_the_secret_files_were_found() -> None:
    assert SECRETS


@pytest.mark.parametrize("path", SECRETS, ids=lambda path: path.name)
def test_each_file_is_encrypted_to_the_declared_recipient_only(path: pathlib.Path) -> None:
    metadata = yaml.safe_load(path.read_text(encoding="utf-8"))["sops"]
    # SOPS writes either form, depending on how the file was last encrypted; both
    # are read, so a recipient in one cannot hide behind the other.
    entries = metadata.get("age", []) + [e for group in metadata.get("key_groups", []) for e in group.get("age", [])]
    recipients = [entry["recipient"] for entry in entries]
    assert RETIRED_CI_RECIPIENT not in recipients
    assert recipients == sorted(_declared())
