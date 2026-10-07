"""Each node gets a bucket, a key pair and a restic password no other node gets (BACKUP-057).

Two halves. AC3, the mint: distinct key pairs alone cannot show isolation,
because four pairs minted from one policy that spans every bucket, or the whole
account, would all differ and all reach every history. So it asserts on the
policy each mint requests from the Cloudflare API: exactly one resource, the
node's own bucket, with Object Read & Write and nothing more. The watcher's read
token names the backup buckets and nothing else.

AC1, the consumers: every consumer uses a node's own bucket, pair and password
once the node is declared in `backup.r2.own_bucket_nodes`, and the shared ones
before that, so the switch happens by declaration and never by the timing of a
merge. Checked against a fixture that declares every node migrated, not against
the live `common.yaml`, which lists none until the migration sitting. The
watcher is the declared exception: one read pair spans every bucket, by design
(proposal *What* §4), so for it the test asserts the opposite of the rule.
"""

from __future__ import annotations

import copy
import pathlib
import re
from typing import Any

import jinja2
import pytest
import yaml

from toolkit.features import backup_node_credentials as bnc
from toolkit.features.backup_destination import (
    node_repository,
    node_restic,
    node_secret_paths,
    own_bucket_nodes,
    render_watcher_targets,
    watcher_password_paths,
)
from toolkit.features.backup_node_credentials import (
    WATCHER_ACCESS_KEY_PATH,
    WATCHER_SECRET_KEY_PATH,
    access_key_path,
    restic_password_path,
    secret_key_path,
    watcher_buckets,
    watcher_token_request,
)
from toolkit.features.r2_tfvars import NODE_BUCKET_PREFIX, node_bucket

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
NODES = sorted(COMMON["backup"]["sources"])
R2 = COMMON["backup"]["r2"]
LEGACY = R2["bucket"]
SHARED_PATHS = ("backup.r2.access_key_id", "backup.r2.secret_access_key", "backup.restic_password")


def _declared(nodes: list[str]) -> dict[str, Any]:
    config = copy.deepcopy(COMMON)
    config["backup"]["r2"]["own_bucket_nodes"] = list(nodes)
    return config


MIGRATED = _declared(NODES)


# ── AC3: what each mint requests ──────────────────────────────────────────────


def _nodes() -> list[str]:
    return sorted(
        yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))["backup"]["sources"]
    )


@pytest.mark.parametrize("node", _nodes())
def test_the_requested_policy_names_exactly_the_nodes_own_bucket(node: str) -> None:
    body = bnc.token_request(node, account_id="acct0123", write_group_id="pg-write")
    assert len(body["policies"]) == 1
    policy = body["policies"][0]
    assert policy["effect"] == "allow"
    assert policy["resources"] == {f"com.cloudflare.edge.r2.bucket.acct0123_default_kubelab-backup-{node}": "*"}
    assert policy["permission_groups"] == [{"id": "pg-write"}]


def test_no_two_nodes_request_the_same_resource() -> None:
    resources = [
        next(
            iter(bnc.token_request(node, account_id="acct0123", write_group_id="pg-write")["policies"][0]["resources"])
        )
        for node in _nodes()
    ]
    assert len(resources) == len(set(resources))


def test_an_account_wide_resource_is_never_requested() -> None:
    for node in _nodes():
        resources = bnc.token_request(node, account_id="acct0123", write_group_id="pg-write")["policies"][0][
            "resources"
        ]
        assert not any(key.startswith("com.cloudflare.api.account") for key in resources)
        assert not any(key.endswith("*") or "_*" in key for key in resources)


def test_the_watcher_policy_names_exactly_the_backup_buckets_read_only() -> None:
    """The node buckets and the shared one, nothing else (the shared one since PR 4)."""
    body = bnc.watcher_token_request(
        _nodes(), legacy_bucket="kubelab-backups", account_id="acct0123", read_group_id="pg-read"
    )
    assert len(body["policies"]) == 1
    policy = body["policies"][0]
    assert set(policy["resources"]) == {
        f"com.cloudflare.edge.r2.bucket.acct0123_default_{bucket}"
        for bucket in [*(f"kubelab-backup-{node}" for node in _nodes()), "kubelab-backups"]
    }
    assert set(policy["resources"].values()) == {"*"}
    assert policy["permission_groups"] == [{"id": "pg-read"}]


# ── the declaration ───────────────────────────────────────────────────────────


def test_the_live_declaration_lists_no_node_until_the_migration_sitting() -> None:
    """PR 4a changes nothing live: every node stays in the shared bucket until its copy is verified."""
    assert own_bucket_nodes(COMMON) == frozenset()


def test_a_declared_node_that_backs_nothing_up_is_refused() -> None:
    with pytest.raises(ValueError, match="ace2"):
        own_bucket_nodes(_declared(["ace2"]))


# ── backup_destination: the repository and the secrets each node uses ─────────


def test_every_migrated_node_has_a_bucket_of_its_own() -> None:
    repos = {node: node_repository(MIGRATED, node) for node in NODES}
    for node, repo in repos.items():
        assert repo == f"s3:{R2['endpoint']}/{node_bucket(node)}", node
        assert f"/{LEGACY}" not in repo, node
    assert len(set(repos.values())) == len(NODES)


def test_an_undeclared_node_keeps_its_shared_repository() -> None:
    """The VPS is the node whose repository name differs from its key: `kubelab-vps`."""
    assert node_repository(COMMON, "vps") == f"{R2['repo_prefix']}/kubelab-vps"
    assert node_repository(COMMON, "rpi3") == f"{R2['repo_prefix']}/rpi3"


def test_every_migrated_node_reads_its_own_pair_and_password() -> None:
    paths = {node: node_secret_paths(MIGRATED, node) for node in NODES}
    for node, (access, secret, password) in paths.items():
        assert (access, secret, password) == (access_key_path(node), secret_key_path(node), restic_password_path(node))
    for kind in range(3):
        assert len({p[kind] for p in paths.values()}) == len(NODES), f"two nodes share secret #{kind}"


def test_an_undeclared_node_reads_the_shared_secrets() -> None:
    config = _declared(["rpi3"])
    assert node_secret_paths(config, "vps") == SHARED_PATHS
    assert node_secret_paths(config, "rpi3") != SHARED_PATHS


# ── the watcher: targets, Secret and token ────────────────────────────────────


def test_the_watcher_targets_follow_the_declaration() -> None:
    rows = {
        line.split()[0]: line.split()[1]
        for line in render_watcher_targets(_declared(["rpi3"])).splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert rows["rpi3"] == f"s3:{R2['endpoint']}/{node_bucket('rpi3')}"
    assert rows["vps"] == f"{R2['repo_prefix']}/kubelab-vps"


def test_the_watcher_gets_each_nodes_own_password_once_it_has_moved() -> None:
    paths = watcher_password_paths(_declared(["rpi3"]))
    assert set(paths) == {f"RESTIC_PASSWORD_{node.upper()}" for node in NODES}
    assert paths["RESTIC_PASSWORD_RPI3"] == restic_password_path("rpi3")
    assert paths["RESTIC_PASSWORD_VPS"] == "backup.restic_password"


def test_every_migrated_password_the_watcher_carries_is_that_nodes_own_key() -> None:
    """Never a copy: the watcher reads the node's SOPS key, so a rotation reaches both."""
    for node, path in ((n, watcher_password_paths(MIGRATED)[f"RESTIC_PASSWORD_{n.upper()}"]) for n in NODES):
        assert path == restic_password_path(node)


def test_the_watcher_secret_maps_each_migrated_node_to_its_own_password() -> None:
    from toolkit.features.k8s_secrets import SECRET_DEFINITIONS, WATCHER_SECRET, _resolve_config_keys

    (mapping,) = [m for m in SECRET_DEFINITIONS if m.name == WATCHER_SECRET]
    keys = _resolve_config_keys(mapping, MIGRATED).keys
    for node in NODES:
        assert keys[f"RESTIC_PASSWORD_{node.upper()}"] == restic_password_path(node).upper().replace(".", "_")
    assert (keys["AWS_ACCESS_KEY_ID"], keys["AWS_SECRET_ACCESS_KEY"]) == (
        WATCHER_ACCESS_KEY_PATH.upper().replace(".", "_"),
        WATCHER_SECRET_KEY_PATH.upper().replace(".", "_"),
    )


def test_the_watcher_pair_is_none_of_the_nodes_pairs() -> None:
    node_paths = {p for node in NODES for p in node_secret_paths(MIGRATED, node)[:2]}
    assert {WATCHER_ACCESS_KEY_PATH, WATCHER_SECRET_KEY_PATH}.isdisjoint(node_paths)


def test_the_watcher_token_reads_every_node_bucket_and_the_shared_one_and_writes_nothing() -> None:
    """The shared bucket stays readable until it is deleted, so the fleet size has no blind spot."""
    assert watcher_buckets(NODES, LEGACY) == sorted([*map(node_bucket, NODES), LEGACY])
    body = watcher_token_request(NODES, legacy_bucket=LEGACY, account_id="acc", read_group_id="read-group")
    (policy,) = body["policies"]
    assert [g["id"] for g in policy["permission_groups"]] == ["read-group"]
    resources = set(policy["resources"])
    for bucket in watcher_buckets(NODES, LEGACY):
        assert any(r.endswith(f"_{bucket}") for r in resources), bucket


# ── the playbook: what each node is given ─────────────────────────────────────


def _regex_replace(value: str, pattern: str, replacement: str = "") -> str:
    return re.sub(pattern, replacement, value)


def _role_vars(config: dict[str, Any], inventory_hostname: str) -> dict[str, str]:
    """Render backup.yml's credential vars for one host, the way Ansible would."""
    play = yaml.safe_load((REPO / "infra/ansible/playbooks/backup.yml").read_text())[0]
    (role,) = [r for r in play["roles"] if str(r.get("role", "")).endswith("node_backup")]
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["regex_replace"] = _regex_replace
    env.filters["bool"] = lambda value: str(value).strip().lower() in ("true", "yes", "1")
    pairs = {n: {"access_key_id": f"{n}-access", "secret_access_key": f"{n}-secret"} for n in NODES}
    secrets = {
        "backup": {
            "restic_password": "shared-password",
            "r2": {"access_key_id": "shared-access", "secret_access_key": "shared-secret", "nodes": pairs},
            "nodes": {n: {"restic_password": f"{n}-password"} for n in NODES},
        }
    }
    context: dict[str, Any] = {"config": config, "secrets": secrets, "inventory_hostname": inventory_hostname}
    for name in ("node_short_name", "node_own_bucket"):
        # Rendered to a string, as Ansible may hand it over: the role vars must survive "False".
        context[name] = env.from_string(play["vars"][name]).render(context)
    keys = (
        "node_backup_r2_repository",
        "node_backup_restic_password",
        "node_backup_r2_access_key",
        "node_backup_r2_secret_key",
    )
    return {k: env.from_string(role["vars"][k]).render(context).strip() for k in keys}


HOSTS = {"beelink": "beelink", "rpi3": "rpi3", "rpi4": "rpi4", "vps": "kubelab-vps"}


def test_the_playbook_gives_every_migrated_node_its_own_bucket_pair_and_password() -> None:
    rendered = {node: _role_vars(MIGRATED, host) for node, host in HOSTS.items()}
    for node, values in rendered.items():
        assert values["node_backup_r2_repository"] == f"s3:{R2['endpoint']}/{NODE_BUCKET_PREFIX}{node}", node
        assert values["node_backup_restic_password"] == f"{node}-password", node
        assert values["node_backup_r2_access_key"] == f"{node}-access", node
        assert values["node_backup_r2_secret_key"] == f"{node}-secret", node


def test_the_playbook_keeps_an_undeclared_node_on_the_shared_bucket() -> None:
    values = _role_vars(_declared(["rpi3"]), "kubelab-vps")
    assert values == {
        "node_backup_r2_repository": f"{R2['repo_prefix']}/kubelab-vps",
        "node_backup_restic_password": "shared-password",
        "node_backup_r2_access_key": "shared-access",
        "node_backup_r2_secret_key": "shared-secret",
    }


# ── the drills and the coverage report: what they read R2 with ────────────────


class _CM:
    """Stands in for ConfigurationManager: records each SOPS path read, returns a value named after it."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config, self.asked = config, []

    def get_merged_config(self) -> dict[str, Any]:
        return self.config

    def get_secret_by_path(self, path: str) -> str:
        self.asked.append(path)
        return f"value-of-{path}"


def test_a_drill_reads_a_migrated_node_with_its_own_pair_and_password() -> None:
    cm = _CM(MIGRATED)
    repo, env = node_restic(cm, "rpi3")
    assert repo == f"s3:{R2['endpoint']}/{node_bucket('rpi3')}"
    assert set(cm.asked) == {access_key_path("rpi3"), secret_key_path("rpi3"), restic_password_path("rpi3")}
    assert env["RESTIC_PASSWORD"] == f"value-of-{restic_password_path('rpi3')}"
    assert env["AWS_ACCESS_KEY_ID"] == f"value-of-{access_key_path('rpi3')}"


def test_a_drill_reads_an_undeclared_node_with_the_shared_secrets() -> None:
    cm = _CM(COMMON)
    repo, env = node_restic(cm, "vps")
    assert repo == f"{R2['repo_prefix']}/kubelab-vps"
    assert set(cm.asked) == set(SHARED_PATHS)
