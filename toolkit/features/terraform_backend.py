"""Render the shared S3 backend settings for every Terraform root (TF-007 AC2).

Each root declares `backend "s3" { key = "<root>/terraform.tfstate" }` and
nothing else. Everything the roots share lives in one file next to them,
`infra/terraform/backend.s3.tfbackend`, rendered from `terraform.state` in
`common.yaml` and passed to every `init` by the runner.

The endpoint is `backup.r2.endpoint`. The state bucket is in the same R2 account
as the backups, so the account's S3 endpoint is one fact, declared once.

Credentials are not here. They reach terraform as AWS_ACCESS_KEY_ID and
AWS_SECRET_ACCESS_KEY in the child's environment, from SOPS, through the runner.
`encrypt` is not here either: it sends an SSE header R2 does not implement, and
R2 encrypts at rest with Cloudflare-managed keys regardless.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

BACKEND_FILE = "backend.s3.tfbackend"


def render(config: Mapping[str, Any]) -> str:
    state = config["terraform"]["state"]
    endpoint = config["backup"]["r2"]["endpoint"]
    return (
        "# Generated from terraform.state in common.yaml by `make sync-terraform-backend`.\n"
        "# Do not edit. Passed to every init by the runner (toolkit/features/terraform_runner.py).\n"
        f'bucket = "{state["bucket"]}"\n'
        'region = "auto"\n'
        f'endpoints = {{ s3 = "{endpoint}" }}\n'
        "use_path_style = true\n"
        # S3-native locking: a conditional PUT of `<key>.tflock`. Measured atomic
        # on R2, 40 trials x 8 writers (2026-10-13); `make test-tfstate-lock-live`.
        "use_lockfile = true\n"
        # R2 is not AWS: there is no STS, no region list and no metadata API to ask.
        "skip_credentials_validation = true\n"
        "skip_region_validation = true\n"
        "skip_requesting_account_id = true\n"
        "skip_metadata_api_check = true\n"
        "skip_s3_checksum = true\n"
    )


def sync(config: Mapping[str, Any], terraform_dir: Path) -> bool:
    """Write the file if it differs from the render. Returns whether it changed."""
    target = terraform_dir / BACKEND_FILE
    content = render(config)
    if target.is_file() and target.read_text(encoding="utf-8") == content:
        return False
    target.write_text(content, encoding="utf-8")
    return True
