"""Terraform's S3 lock is only as good as R2's conditional PUT (TF-007).

`use_lockfile` takes the lock by putting `<key>.tflock` with `If-None-Match: *`.
If two writers could both succeed, two applies would run against one state at
once. Measured atomic on 2026-10-13 (40 trials x 8 writers); this re-measures it
against the real state bucket with the state's own credentials, under a `probe/`
prefix the history lock rule does not cover, and removes what it wrote.

Run with `make test-tfstate-lock-live`. Skipped without the credentials.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.infra

TRIALS = 10
WRITERS = 8


@pytest.fixture(scope="module")
def r2() -> dict[str, Any]:
    from toolkit.features.backup_node_credentials import _s3_env
    from toolkit.features.configuration import ConfigurationManager

    config = ConfigurationManager("common").get_merged_config()
    state = (config.get("terraform") or {}).get("state") or {}
    if not state.get("access_key_id"):
        pytest.skip("terraform.state credentials are not in SOPS yet: make tf-state-bootstrap")
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(_s3_env(str(state["access_key_id"]), str(state["secret_access_key"])))
    return {"env": env, "bucket": state["bucket"], "endpoint": config["backup"]["r2"]["endpoint"]}


def _aws(r2: dict[str, Any], *args: str) -> subprocess.CompletedProcess[str]:
    argv = ["aws", "--endpoint-url", r2["endpoint"], "s3api", *args, "--bucket", r2["bucket"]]
    return subprocess.run(argv, env=r2["env"], capture_output=True, text=True, timeout=60, check=False)


def test_exactly_one_of_many_concurrent_lock_takers_wins(r2: dict[str, Any]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        body = Path(tmp) / "lock"
        body.write_text("{}")
        for _ in range(TRIALS):
            key = f"probe/{uuid.uuid4()}.tflock"
            try:
                with ThreadPoolExecutor(WRITERS) as pool:
                    put = ("put-object", "--key", key, "--body", str(body), "--if-none-match", "*")
                    results = list(pool.map(lambda args: _aws(r2, *args), [put] * WRITERS))
            finally:
                _aws(r2, "delete-object", "--key", key)
            winners = [r for r in results if r.returncode == 0]
            losers = [r for r in results if r.returncode != 0]
            assert len(winners) == 1, f"{len(winners)} writers took the lock on {key}"
            assert all("PreconditionFailed" in r.stderr for r in losers), [r.stderr[-200:] for r in losers]
