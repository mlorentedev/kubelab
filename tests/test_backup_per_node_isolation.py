"""Each node gets a bucket, a key pair and a restic password no other node gets (BACKUP-057).

Two halves. AC3, the mint: distinct key pairs alone cannot show isolation,
because four pairs minted from one policy that spans every bucket, or the whole
account, would all differ and all reach every history. So it asserts on the
policy each mint requests from the Cloudflare API: exactly one resource, the
node's own bucket, with Object Read & Write and nothing more. The watcher's read
token names the backup buckets and nothing else.

AC1, the consumers: every consumer uses a node's own bucket, pair and password,
unconditionally. The shared bucket's pair and password are not even offered to
the playbook's render, so a consumer that fell back to them would fail on an
undefined variable instead of quietly shipping to the wrong bucket. The watcher
is the declared exception: one read pair spans every bucket, by design
(proposal *What* §4), so for it the test asserts the opposite of the rule.
"""

from __future__ import annotations

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
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
NODES = sorted(COMMON["backup"]["sources"])
R2 = COMMON["backup"]["r2"]
# The shared bucket's pair and password, retired with it (#1920): no node may read them again.
SHARED_PATHS = ("backup.r2.access_key_id", "backup.r2.secret_access_key", "backup.restic_password")


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
    """The node buckets, nothing else: the shared bucket was retired (#1920)."""
    body = bnc.watcher_token_request(_nodes(), account_id="acct0123", read_group_id="pg-read")
    assert len(body["policies"]) == 1
    policy = body["policies"][0]
    assert set(policy["resources"]) == {
        f"com.cloudflare.edge.r2.bucket.acct0123_default_{bucket}"
        for bucket in (f"kubelab-backup-{node}" for node in _nodes())
    }
    assert set(policy["resources"].values()) == {"*"}
    assert policy["permission_groups"] == [{"id": "pg-read"}]


# ── the declaration ───────────────────────────────────────────────────────────


def test_no_node_is_declared_in_or_out_of_its_own_bucket() -> None:
    """Every node in `backup.sources` ships to its own bucket; there is no list that says which.

    ace2 was born there (spec AI-009 AC7) and the other four moved on 2026-10-08.
    A list that can leave a node out is a branch that can ship it to the old
    bucket again, which is the thing this guards.
    """
    assert "own_bucket_nodes" not in R2


# ── backup_destination: the repository and the secrets each node uses ─────────


def test_every_node_has_a_bucket_of_its_own() -> None:
    repos = {node: node_repository(COMMON, node) for node in NODES}
    for node, repo in repos.items():
        assert repo == f"s3:{R2['endpoint']}/{node_bucket(node)}", node
    assert len(set(repos.values())) == len(NODES)


def test_every_node_reads_its_own_pair_and_password() -> None:
    paths = {node: node_secret_paths(node) for node in NODES}
    for node, (access, secret, password) in paths.items():
        assert (access, secret, password) == (access_key_path(node), secret_key_path(node), restic_password_path(node))
    for kind in range(3):
        assert len({p[kind] for p in paths.values()}) == len(NODES), f"two nodes share secret #{kind}"


def test_no_node_reads_the_shared_secrets() -> None:
    for node in NODES:
        assert not set(node_secret_paths(node)) & set(SHARED_PATHS), node


# ── the watcher: targets, Secret and token ────────────────────────────────────


def test_the_watcher_targets_name_each_nodes_own_bucket() -> None:
    rows = {
        line.split()[0]: line.split()[1]
        for line in render_watcher_targets(COMMON).splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert rows == {node: f"s3:{R2['endpoint']}/{node_bucket(node)}" for node in NODES}


def test_the_watcher_gets_each_nodes_own_password() -> None:
    paths = watcher_password_paths(COMMON)
    assert paths == {f"RESTIC_PASSWORD_{node.upper()}": restic_password_path(node) for node in NODES}
    assert "backup.restic_password" not in paths.values()


def test_every_password_the_watcher_carries_is_that_nodes_own_key() -> None:
    """Never a copy: the watcher reads the node's SOPS key, so a rotation reaches both."""
    for node, path in ((n, watcher_password_paths(COMMON)[f"RESTIC_PASSWORD_{n.upper()}"]) for n in NODES):
        assert path == restic_password_path(node)


def test_the_watcher_secret_maps_each_node_to_its_own_password() -> None:
    from toolkit.features.k8s_secrets import SECRET_DEFINITIONS, WATCHER_SECRET, _resolve_config_keys

    (mapping,) = [m for m in SECRET_DEFINITIONS if m.name == WATCHER_SECRET]
    keys = _resolve_config_keys(mapping, COMMON).keys
    for node in NODES:
        assert keys[f"RESTIC_PASSWORD_{node.upper()}"] == restic_password_path(node).upper().replace(".", "_")
    assert (keys["AWS_ACCESS_KEY_ID"], keys["AWS_SECRET_ACCESS_KEY"]) == (
        WATCHER_ACCESS_KEY_PATH.upper().replace(".", "_"),
        WATCHER_SECRET_KEY_PATH.upper().replace(".", "_"),
    )


def test_the_watcher_pair_is_none_of_the_nodes_pairs() -> None:
    node_paths = {p for node in NODES for p in node_secret_paths(node)[:2]}
    assert {WATCHER_ACCESS_KEY_PATH, WATCHER_SECRET_KEY_PATH}.isdisjoint(node_paths)


def test_the_watcher_token_reads_every_node_bucket_and_writes_nothing() -> None:
    assert watcher_buckets(NODES) == sorted(map(node_bucket, NODES))
    body = watcher_token_request(NODES, account_id="acc", read_group_id="read-group")
    (policy,) = body["policies"]
    assert [g["id"] for g in policy["permission_groups"]] == ["read-group"]
    resources = set(policy["resources"])
    for bucket in watcher_buckets(NODES):
        assert any(r.endswith(f"_{bucket}") for r in resources), bucket


# ── the playbook: what each node is given ─────────────────────────────────────


def _regex_replace(value: str, pattern: str, replacement: str = "") -> str:
    return re.sub(pattern, replacement, value)


def _put(tree: dict[str, Any], dotted: str, value: str) -> None:
    *parents, leaf = dotted.split(".")
    for key in parents:
        tree = tree.setdefault(key, {})
    tree[leaf] = value


def _role_vars(config: dict[str, Any], inventory_hostname: str) -> dict[str, str]:
    """Render backup.yml's credential vars for one host, the way Ansible would."""
    play = yaml.safe_load((REPO / "infra/ansible/playbooks/backup.yml").read_text(encoding="utf-8"))[0]
    (role,) = [r for r in play["roles"] if str(r.get("role", "")).endswith("node_backup")]
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["regex_replace"] = _regex_replace
    # Built from the toolkit's own key paths, so a key the toolkit moves is a
    # key the playbook no longer finds, and this test goes red.
    secrets: dict[str, Any] = {}
    # The shared pair and password are deliberately absent: StrictUndefined then
    # fails the render of any var that reads them.
    for n in NODES:
        _put(secrets, access_key_path(n), f"{n}-access")
        _put(secrets, secret_key_path(n), f"{n}-secret")
        _put(secrets, restic_password_path(n), f"fixture-{n}")
    context: dict[str, Any] = {"config": config, "secrets": secrets, "inventory_hostname": inventory_hostname}
    assert "node_own_bucket" not in play["vars"]
    context["node_short_name"] = env.from_string(play["vars"]["node_short_name"]).render(context)
    keys = (
        "node_backup_r2_repository",
        "node_backup_restic_password",
        "node_backup_r2_access_key",
        "node_backup_r2_secret_key",
    )
    return {k: env.from_string(role["vars"][k]).render(context).strip() for k in keys}


HOSTS = {"ace2": "ace2", "beelink": "beelink", "rpi3": "rpi3", "rpi4": "rpi4", "vps": "kubelab-vps"}


def test_the_playbook_gives_every_node_its_own_bucket_pair_and_password() -> None:
    rendered = {node: _role_vars(COMMON, host) for node, host in HOSTS.items()}
    for node, values in rendered.items():
        assert values["node_backup_r2_repository"] == f"s3:{R2['endpoint']}/{NODE_BUCKET_PREFIX}{node}", node
        assert values["node_backup_restic_password"] == f"fixture-{node}", node
        assert values["node_backup_r2_access_key"] == f"{node}-access", node
        assert values["node_backup_r2_secret_key"] == f"{node}-secret", node


def test_the_hosts_this_test_renders_are_every_node_that_backs_up() -> None:
    assert {node for node in HOSTS} == set(NODES)


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


def test_a_drill_reads_a_node_with_its_own_pair_and_password() -> None:
    cm = _CM(COMMON)
    repo, env = node_restic(cm, "rpi3")
    assert repo == f"s3:{R2['endpoint']}/{node_bucket('rpi3')}"
    assert set(cm.asked) == {access_key_path("rpi3"), secret_key_path("rpi3"), restic_password_path("rpi3")}
    assert env["RESTIC_PASSWORD"] == f"value-of-{restic_password_path('rpi3')}"
    assert env["AWS_ACCESS_KEY_ID"] == f"value-of-{access_key_path('rpi3')}"


# ── the bucket other tokens are proven refused on ────────────────────────────


def test_the_refusal_proof_names_a_node_bucket_now_the_shared_one_is_gone() -> None:
    """The documents and state tokens prove they cannot read the backups (#1920)."""
    assert bnc.backup_bucket_to_refuse(COMMON) == node_bucket(NODES[0])
    assert bnc.backup_bucket_to_refuse({"backup": {}}) == ""
