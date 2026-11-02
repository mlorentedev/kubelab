"""Every root keeps its state in R2, configured from one place (TF-007 AC1, AC2).

The roots used `backend "local"`, so a root's state lived in whichever checkout
last ran `apply`. Three roots lost theirs that way and #1499 saw the other side
of it: a plan from a fresh worktree read an empty state and proposed recreating
every DNS record.

Each root now declares only its key. The shared settings are one generated file,
`infra/terraform/backend.s3.tfbackend`, which the runner passes to every
`init`. A root initialised without it stops and asks for the bucket, which is
the point: there is no setting under which it quietly falls back to a local file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from toolkit.features import terraform_backend as tb
from toolkit.features import terraform_runner as tr

REPO = Path(__file__).resolve().parent.parent
TERRAFORM_DIR = REPO / "infra" / "terraform"
CONFIG = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text(encoding="utf-8"))


def _terraform_block(root: str) -> str:
    text = "\n".join((TERRAFORM_DIR / root / f).read_text(encoding="utf-8") for f in _tf_files(root))
    match = re.search(r"^terraform \{\n(.*?)^\}", text, re.M | re.S)
    assert match, f"{root} has no terraform block"
    return match.group(1)


def _tf_files(root: str) -> list[str]:
    return sorted(p.name for p in (TERRAFORM_DIR / root).glob("*.tf"))


# --------------------------------------------------------------------------- AC1


@pytest.mark.parametrize("root", sorted(tr.ROOTS))
def test_each_root_declares_only_its_key_in_an_s3_backend(root: str) -> None:
    block = _terraform_block(root)
    backends = re.findall(r'^\s*backend "(\w+)" \{(.*?)^\s*\}', block, re.M | re.S)
    assert len(backends) == 1, backends
    kind, body = backends[0]
    assert kind == "s3"
    settings = dict(re.findall(r'^\s*(\w+)\s*=\s*"([^"]*)"', body, re.M))
    # Only the key: everything shared comes from the generated file, so a root
    # cannot point at a different bucket by editing its own block.
    assert settings == {"key": f"{root}/terraform.tfstate"}, settings


def test_no_terraform_file_anywhere_declares_a_local_backend() -> None:
    offenders = [
        str(p.relative_to(REPO))
        for p in TERRAFORM_DIR.rglob("*.tf")
        if re.search(r'backend\s+"local"', p.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders


@pytest.mark.parametrize("root", sorted(tr.ROOTS))
def test_each_root_requires_a_terraform_that_has_s3_locking(root: str) -> None:
    """`use_lockfile` arrived in 1.10; an older binary ignores it and runs unlocked."""
    match = re.search(r'required_version\s*=\s*">=\s*(\d+)\.(\d+)', _terraform_block(root))
    assert match and (int(match.group(1)), int(match.group(2))) >= (1, 10), root


# --------------------------------------------------------------------------- AC2


def test_the_committed_backend_file_is_the_render_of_the_ssot() -> None:
    committed = (TERRAFORM_DIR / tb.BACKEND_FILE).read_text(encoding="utf-8")
    assert committed == tb.render(CONFIG), "run `make sync-terraform-backend`"


def test_the_backend_file_carries_no_credential_and_no_encrypt() -> None:
    """Credentials reach terraform as AWS_* in the child's environment only.
    `encrypt = true` sends an SSE header R2 does not implement."""
    text = tb.render(CONFIG)
    assert not re.search(r"(access_key|secret_key|token|profile|encrypt)\s*=", text), text


def test_the_backend_points_at_the_state_bucket_with_s3_locking() -> None:
    text = tb.render(CONFIG)
    assert f'bucket = "{CONFIG["terraform"]["state"]["bucket"]}"' in text
    assert "use_lockfile = true" in text
    assert f'endpoints = {{ s3 = "{CONFIG["backup"]["r2"]["endpoint"]}" }}' in text


def test_the_render_refuses_a_missing_bucket() -> None:
    with pytest.raises(KeyError):
        tb.render({**CONFIG, "terraform": {"state": {}}})


def test_the_sync_writes_the_file_and_a_second_run_changes_nothing(tmp_path: Path) -> None:
    assert tb.sync(CONFIG, tmp_path) is True
    assert (tmp_path / tb.BACKEND_FILE).read_text(encoding="utf-8") == tb.render(CONFIG)
    assert tb.sync(CONFIG, tmp_path) is False
