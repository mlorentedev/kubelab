"""`make backup-coverage` names every live claim with no backup ruling (BACKUP-046 AC4).

`tests/test_backup_pvc_coverage.py` covers the claims the prod overlay renders.
It cannot see a claim created anywhere else: `kube-system/traefik` comes from
K3s's own Helm chart, configured by Ansible. Only the cluster knows those, so
this half reads it.

A cluster the command cannot read is CANNOT CHECK, which fails. It never
passes, because "no unruled claims" and "did not look" must not print the same.
"""

from __future__ import annotations

import json
from pathlib import Path

from toolkit.features.backup_destination import check_claim_rulings, cluster_node, unruled_claims

BACKUP = {
    "sources": {"vps": {"n8n": {"pvc": {"namespace": "kubelab", "claim": "n8n-data"}, "sqlite": ["x.sqlite"]}}},
    "excluded": {
        "vps": {"loki": {"pvc": {"namespace": "kubelab", "claim": "loki-data"}, "reason": "r", "tier": 3}},
        "beelink": {"runner": {"volume": "runner", "reason": "r", "tier": 3}},
    },
}
CONFIG = {
    "backup": BACKUP,
    "networking": {
        "vps": {"ansible_groups": ["vps", "k3s_servers"]},
        "nodes": {"ace1": {"ansible_groups": ["minipc"]}, "rpi4": {}},
    },
}


def _pvc_list(*claims: tuple[str, str]) -> str:
    return json.dumps({"items": [{"metadata": {"namespace": ns, "name": name}} for ns, name in claims]})


def test_the_cluster_node_is_the_one_in_k3s_servers() -> None:
    assert cluster_node(CONFIG) == "vps"


def test_two_cluster_nodes_resolve_to_none_rather_than_a_guess() -> None:
    config = {"networking": {**CONFIG["networking"], "nodes": {"ace1": {"ansible_groups": ["k3s_servers"]}}}}
    assert cluster_node(config) is None


def test_a_claim_in_neither_list_is_unruled() -> None:
    live = {("kubelab", "n8n-data"), ("kubelab", "loki-data"), ("kube-system", "traefik")}
    assert unruled_claims(BACKUP, "vps", live) == [("kube-system", "traefik")]


def test_another_nodes_exclusions_do_not_rule_this_nodes_claims() -> None:
    assert unruled_claims(BACKUP, "vps", {("kubelab", "runner")}) == [("kubelab", "runner")]


class _Run:
    def __init__(self, rc: int, out: str, err: str = "") -> None:
        self.result = (rc, out, err)
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        self.calls.append(argv)
        return self.result


def _kubeconfig(tmp_path: Path) -> Path:
    path = tmp_path / "kubeconfig"
    path.write_text("apiVersion: v1\n")
    return path


def test_every_live_claim_ruled_passes(tmp_path: Path) -> None:
    run = _Run(0, _pvc_list(("kubelab", "n8n-data"), ("kubelab", "loki-data")))
    assert check_claim_rulings(CONFIG, _kubeconfig(tmp_path), run) is True
    [argv] = run.calls
    assert argv[:3] == ["kubectl", "--kubeconfig", str(tmp_path / "kubeconfig")]
    assert argv[3:] == ["get", "pvc", "--all-namespaces", "-o", "json"]


def test_an_unruled_live_claim_fails_and_is_named(tmp_path: Path, capsys) -> None:
    run = _Run(0, _pvc_list(("kubelab", "n8n-data"), ("kube-system", "traefik")))
    assert check_claim_rulings(CONFIG, _kubeconfig(tmp_path), run) is False
    assert "kube-system/traefik" in capsys.readouterr().out


def test_a_missing_kubeconfig_is_cannot_check_not_a_pass(tmp_path: Path, capsys) -> None:
    run = _Run(0, _pvc_list())
    assert check_claim_rulings(CONFIG, tmp_path / "absent", run) is False
    assert "CANNOT CHECK" in capsys.readouterr().out
    assert run.calls == []


def test_an_unreadable_cluster_is_cannot_check_not_a_pass(tmp_path: Path, capsys) -> None:
    run = _Run(1, "", "Unable to connect to the server")
    assert check_claim_rulings(CONFIG, _kubeconfig(tmp_path), run) is False
    assert "CANNOT CHECK" in capsys.readouterr().out


def test_an_empty_answer_is_cannot_check_not_a_pass(tmp_path: Path, capsys) -> None:
    """A cluster with state always has claims; zero means the read went wrong (lesson-416)."""
    assert check_claim_rulings(CONFIG, _kubeconfig(tmp_path), _Run(0, _pvc_list())) is False
    assert "CANNOT CHECK" in capsys.readouterr().out


def test_a_cluster_node_with_no_backups_declared_is_reported_and_skipped(tmp_path: Path, capsys) -> None:
    config = {**CONFIG, "backup": {"sources": {}, "excluded": {}}}
    run = _Run(0, _pvc_list(("kubelab", "n8n-data")))
    assert check_claim_rulings(config, _kubeconfig(tmp_path), run) is True
    assert "declares no backups" in capsys.readouterr().out
    assert run.calls == []


def test_an_ambiguous_cluster_node_fails(tmp_path: Path, capsys) -> None:
    config = {
        **CONFIG,
        "networking": {
            "vps": {"ansible_groups": ["k3s_servers"]},
            "nodes": {"ace1": {"ansible_groups": ["k3s_servers"]}},
        },
    }
    assert check_claim_rulings(config, _kubeconfig(tmp_path), _Run(0, _pvc_list())) is False


class _CM:
    def get_merged_config(self) -> dict:
        r2 = {"account_id": "a", "bucket": "b", "endpoint": "https://e"}
        return {**CONFIG, "backup": {**BACKUP, "r2": r2}}

    def get_secret_by_path(self, path: str) -> str:
        return "not-a-real-value"


def test_coverage_fails_on_an_unruled_claim_even_when_every_snapshot_is_fresh(tmp_path: Path) -> None:
    from toolkit.features.backup_destination import coverage

    snapshot = json.dumps([{"time": "2026-10-01T06:00:00Z", "paths": ["/opt/node-backup/staging"]}])

    def run(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        if argv[0] == "kubectl":
            return 0, _pvc_list(("kubelab", "n8n-data"), ("kube-system", "traefik")), ""
        return 0, snapshot, ""

    assert coverage(env="prod", cm=_CM(), run=run, kubeconfig=_kubeconfig(tmp_path)) is False
