"""`make backup-migrate` moves one node into its own bucket, and stops at the first failure (BACKUP-057 AC4).

restic, the Cloudflare API, Ansible and the values file are all faked. What is
asserted is the order of the steps, that the temporary token never outlives
the copy, and that a copy is only trusted when every source snapshot has
exactly one copy: a count and an oldest time that agree prove neither.
"""

from __future__ import annotations

import copy
import json
import pathlib
import shutil
from typing import Any

import pytest
import yaml

from toolkit.features import backup_migrate as bm
from toolkit.features.backup_node_credentials import (
    MINTER_KEY,
    access_key_path,
    restic_password_path,
    secret_key_path,
)
from toolkit.features.r2_tfvars import node_bucket

REPO = pathlib.Path(__file__).resolve().parents[1]
ACCOUNT = "acct"
ENDPOINT = "https://acct.r2.cloudflarestorage.com"
PREFIX = f"s3:{ENDPOINT}/kubelab-backups"
NODES = ["beelink", "rpi3", "rpi4", "vps"]
NEW_ID = "a" * 64


def _config() -> dict[str, Any]:
    return {
        "backup": {
            "sources": dict.fromkeys(NODES, {}),
            "r2": {
                "account_id": ACCOUNT,
                "endpoint": ENDPOINT,
                "bucket": "kubelab-backups",
                "repo_prefix": PREFIX,
                "own_bucket_nodes": [],
                "repository_ids": {n: "0" * 64 for n in NODES},
            },
        },
        "networking": {"vps": {"hostname": "kubelab-vps"}, "nodes": {n: {"hostname": n} for n in NODES[:3]}},
    }


class _CM:
    def __init__(self) -> None:
        self.config = _config()
        self.secrets = {
            MINTER_KEY: "minter",
            "backup.r2.access_key_id": "shared-id",
            "backup.r2.secret_access_key": "shared-key",
            "backup.restic_password": "fixture-shared",
        }
        for n in NODES:
            self.secrets |= {
                access_key_path(n): f"{n}-id",
                secret_key_path(n): f"{n}-key",
                restic_password_path(n): f"fixture-{n}",
            }
        self.project_root = REPO

    def get_merged_config(self) -> dict[str, Any]:
        return copy.deepcopy(self.config)

    def get_secret_by_path(self, path: str) -> str | None:
        return self.secrets.get(path)


def _snap(snap_id: str, original: str | None = None, time: str = "2026-10-01T00:00:00Z") -> dict[str, Any]:
    entry: dict[str, Any] = {"id": snap_id, "short_id": snap_id[:8], "time": time}
    if original:
        entry["original"] = original
    return entry


class World:
    """One fake of everything the migration touches, recording what it was asked, in order."""

    def __init__(self, source: list[dict[str, Any]], copied: list[dict[str, Any]]) -> None:
        self.source, self.copied = source, copied
        self.calls: list[str] = []
        self.restic_env: dict[str, dict[str, str]] = {}
        self.fail: set[str] = set()
        self.values: list[tuple[str, ...]] = []

    def run(self, argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        if argv[0] == "aws":
            bucket = argv[argv.index("--bucket") + 1]
            self.calls.append(f"aws list {bucket}")
            readable = {"kubelab-backups", node_bucket("rpi3")}
            return (0, "{}", "") if bucket in readable else (254, "", "An error occurred (AccessDenied)")
        repo = argv[argv.index("-r") + 1]
        side = "src" if repo.startswith(PREFIX) else "dst"
        verb = argv[3]
        step = f"restic {side} {verb}"
        self.calls.append(step)
        self.restic_env[step] = env
        if step in self.fail:
            return 1, "", f"{verb} failed"
        if verb == "snapshots":
            return 0, json.dumps(self.source if side == "src" else self.copied), ""
        if verb == "cat":
            return 0, json.dumps({"version": 2, "id": NEW_ID}), ""
        return 0, "", ""

    def http(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        if path.endswith("/permission_groups"):
            return [
                {"name": "Workers R2 Storage Bucket Item Read", "id": "g-read"},
                {"name": "Workers R2 Storage Bucket Item Write", "id": "g-write"},
            ]
        self.calls.append(f"{method} token")
        if method == "POST":
            self.token_body = body
            return {"id": "tmp-id", "value": "tmp-value"}
        return None

    def playbook(self, name: str, limit: str, extra_vars: dict[str, str]) -> bool:
        self.calls.append(f"ansible {name} {limit}")
        return f"ansible {name}" not in self.fail

    def declare(self, node: str) -> None:
        self.calls.append(f"declare {node}")
        self.values.append(("declare", node))

    def pin(self, node: str, repository_id: str) -> None:
        self.calls.append(f"pin {node}")
        self.values.append(("pin", node, repository_id))


SOURCE = [_snap("s1"), _snap("s2", original="o2"), _snap("s3", time="2026-10-02T00:00:00Z")]
COPIED = [
    _snap("c1", original="s1"),
    _snap("c2", original="o2"),
    _snap("c3", original="s3", time="2026-10-02T00:00:00Z"),
]


def _migrate(world: World, **kwargs: Any) -> bool:
    return bm.migrate(
        "rpi3",
        env=kwargs.pop("env", "prod"),
        cm=kwargs.pop("cm", _CM()),
        run=world.run,
        http=world.http,
        playbook=world.playbook,
        values=world,
        regenerate=lambda config: world.calls.append("regenerate targets"),
        sleep=lambda _s: None,
        **kwargs,
    )


def test_the_steps_run_in_order_and_the_token_dies_with_the_copy() -> None:
    world = World(SOURCE, COPIED)
    assert _migrate(world) is True
    assert [c for c in world.calls if not c.startswith("aws")] == [
        "POST token",
        "restic dst init",
        "restic dst copy",
        "restic src snapshots",
        "restic dst snapshots",
        "DELETE token",
        "declare rpi3",
        "ansible backup rpi3",
        "ansible backup-repo-reinit rpi3",
        "ansible backup-node rpi3",
        "restic dst cat",
        "pin rpi3",
        "regenerate targets",
    ]
    assert ("pin", "rpi3", NEW_ID) in world.values


def test_a_missing_snapshot_stops_it_though_the_count_and_oldest_time_match() -> None:
    # s2 has no copy; s1 has two. Three and three, same oldest time.
    copied = [_snap("c1", original="s1"), _snap("c1b", original="s1"), COPIED[2]]
    world = World(SOURCE, copied)
    assert _migrate(world) is False
    assert "DELETE token" in world.calls
    assert not [c for c in world.calls if c.startswith(("declare", "ansible", "pin"))]


@pytest.mark.parametrize("step", ["restic dst init", "restic dst copy", "restic src snapshots"])
def test_a_failed_restic_step_revokes_the_token_and_changes_nothing(step: str) -> None:
    world = World(SOURCE, COPIED)
    world.fail.add(step)
    assert _migrate(world) is False
    assert world.calls[-1] == "DELETE token"
    assert world.values == []


@pytest.mark.parametrize("playbook", ["backup", "backup-repo-reinit", "backup-node"])
def test_a_failed_playbook_stops_before_the_pin(playbook: str) -> None:
    world = World(SOURCE, COPIED)
    world.fail.add(f"ansible {playbook}")
    assert _migrate(world) is False
    assert world.calls[-1] == f"ansible {playbook} rpi3"
    assert not any(v[0] == "pin" for v in world.values)


def test_the_copy_reads_with_the_shared_secrets_and_writes_with_the_nodes() -> None:
    world = World(SOURCE, COPIED)
    assert _migrate(world) is True
    copy_env = world.restic_env["restic dst copy"]
    assert copy_env["AWS_ACCESS_KEY_ID"] == "tmp-id"
    assert copy_env["RESTIC_PASSWORD"] == "fixture-rpi3"
    assert copy_env["RESTIC_FROM_PASSWORD"] == "fixture-shared"
    assert world.restic_env["restic src snapshots"]["RESTIC_PASSWORD"] == "fixture-shared"
    # The id is read back the way the node will read it: its own pair and password.
    cat_env = world.restic_env["restic dst cat"]
    assert (cat_env["AWS_ACCESS_KEY_ID"], cat_env["RESTIC_PASSWORD"]) == ("rpi3-id", "fixture-rpi3")


def test_the_temporary_token_reads_the_shared_bucket_and_writes_only_the_nodes() -> None:
    body = bm.migration_token_request(
        "rpi3", legacy_bucket="kubelab-backups", account_id=ACCOUNT, read_group_id="g-read", write_group_id="g-write"
    )
    grants = {
        group["id"]: sorted(key.rsplit("_default_", 1)[1] for key in policy["resources"])
        for policy in body["policies"]
        for group in policy["permission_groups"]
    }
    assert grants == {"g-read": ["kubelab-backups"], "g-write": [node_bucket("rpi3")]}


def test_a_token_that_reaches_another_nodes_bucket_is_revoked_before_any_copy() -> None:
    world = World(SOURCE, COPIED)
    real_run = world.run

    def too_wide(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        if argv[0] == "aws":
            world.calls.append("aws list")
            return 0, "{}", ""
        return real_run(argv, env)

    world.run = too_wide  # type: ignore[method-assign]
    assert _migrate(world) is False
    assert "DELETE token" in world.calls
    assert not [c for c in world.calls if c.startswith("restic")]


def test_a_dry_run_lists_the_source_and_changes_nothing() -> None:
    world = World(SOURCE, COPIED)
    assert _migrate(world, check=True) is True
    assert world.calls == ["restic src snapshots"]
    assert world.values == []


def test_only_prod_and_only_an_undeclared_node() -> None:
    world = World(SOURCE, COPIED)
    assert _migrate(world, env="staging") is False
    cm = _CM()
    cm.config["backup"]["r2"]["own_bucket_nodes"] = ["rpi3"]
    assert _migrate(world, cm=cm) is False
    assert world.calls == []


@pytest.mark.parametrize(
    ("copied", "unmatched"),
    [
        (COPIED, []),
        (COPIED[:2], ["s3"]),
        ([*COPIED, _snap("c4", original="s3")], ["s3"]),
        ([_snap("c2", original="s2"), *COPIED[::2]], ["s2"]),  # s2's own id is not its key: its original is
    ],
)
def test_every_source_snapshot_needs_exactly_one_copy(copied: list[dict[str, Any]], unmatched: list[str]) -> None:
    assert bm.unmatched_snapshots(SOURCE, copied) == unmatched


def test_the_values_file_keeps_its_comments(tmp_path: pathlib.Path) -> None:
    common = tmp_path / "common.yaml"
    shutil.copy(REPO / "infra/config/values/common.yaml", common)
    values = bm.ValuesFile(common)

    values.declare("rpi3")
    values.pin("rpi3", NEW_ID)

    text = common.read_text()
    loaded = yaml.safe_load(text)["backup"]["r2"]
    assert loaded["own_bucket_nodes"] == ["rpi3"]
    assert loaded["repository_ids"]["rpi3"] == NEW_ID
    assert "# Pinned static binary (BACKUP-044 Part 2)" in text
    original = (REPO / "infra/config/values/common.yaml").read_text().splitlines()
    assert len(text.splitlines()) == len(original)


def test_the_make_target_is_one_node_prod_only_and_threads_the_dry_run() -> None:
    recipe = (REPO / "Makefile").read_text().split("\nbackup-migrate:\n", 1)[1].split("\n\n", 1)[0]
    assert '"$(ENV)" = prod' in recipe
    assert '"$(NODE)" != "all"' in recipe
    assert "$(if $(CHECK),--check)" in recipe
    # Any other value is refused: CHECK=0 must not read as a dry run, and CHECK=yes
    # must not read as the real one.
    assert """test -z "$(CHECK)" -o "$(CHECK)" = 1 ||""" in recipe


@pytest.mark.parametrize(("check", "refused"), [("0", True), ("yes", True), ("1", False), ("", False)])
def test_the_make_target_refuses_an_ambiguous_check(check: str, refused: bool) -> None:
    import subprocess

    recipe = (REPO / "Makefile").read_text().split("\nbackup-migrate:\n", 1)[1].split("\n\n", 1)[0]
    guard = next(line for line in recipe.splitlines() if "CHECK takes" in line).strip().lstrip("@")
    proc = subprocess.run(["sh", "-c", guard.replace("$(CHECK)", check)], capture_output=True, check=False)
    assert (proc.returncode != 0) is refused
