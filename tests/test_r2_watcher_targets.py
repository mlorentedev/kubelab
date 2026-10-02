"""The R2 watcher's targets are generated from `backup.sources`, never hand-written (BACKUP-055 AC4).

The watcher checks, per node, that the newest snapshot holds every declared
source. Its list of what to expect is therefore a copy of `backup.sources`, and
a copy that is edited by hand drifts: a new source is declared, the node starts
backing it up, and the watcher keeps checking the old list — green, and wrong
by omission. So the file is rendered, and this test fails when the committed
render and the SSOT disagree.

The repository name is not the `backup.sources` key (`vps` lives at
`kubelab-vps/` in the bucket), which is the second reason it is derived rather
than typed: `repository_name()` already carries that mapping and the lesson
behind it.
"""

from __future__ import annotations

import pathlib

import yaml

import pytest

from toolkit.features.backup_destination import WATCHER_TARGETS_PATH, render_watcher_targets

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())


def _rows(text: str) -> dict[str, list[str]]:
    rows = {}
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            node, repository, repository_id, *rest = line.split()
            rows[node] = [repository, repository_id, *rest]
    return rows


def test_the_committed_targets_match_the_ssot() -> None:
    committed = (REPO / WATCHER_TARGETS_PATH).read_text()
    assert committed == render_watcher_targets(COMMON), (
        f"{WATCHER_TARGETS_PATH} is stale. Regenerate it with `make sync-r2-watcher-targets`."
    )


def test_every_declared_node_and_source_is_a_target() -> None:
    # Guards the guard: a renderer that emitted nothing would equal an empty file.
    rows = _rows(render_watcher_targets(COMMON))
    sources = COMMON["backup"]["sources"]
    assert set(rows) == set(sources)
    for node, declared in sources.items():
        assert sorted(rows[node][5:]) == sorted(declared), node


def test_the_vps_targets_its_real_repository() -> None:
    assert _rows(render_watcher_targets(COMMON))["vps"][0] == COMMON["backup"]["r2"]["repo_prefix"] + "/kubelab-vps"


def test_every_repository_is_a_restic_s3_url_in_the_backup_bucket() -> None:
    for node, row in _rows(render_watcher_targets(COMMON)).items():
        assert row[0].startswith("s3:https://"), node
        assert f"/{COMMON['backup']['r2']['bucket']}/" in row[0], node


def test_a_new_source_changes_the_render() -> None:
    mutated = yaml.safe_load(yaml.safe_dump(COMMON))
    mutated["backup"]["sources"]["rpi3"]["canary"] = {"path": "/opt/canary"}
    assert "canary" in _rows(render_watcher_targets(mutated))["rpi3"]


def test_the_watcher_reads_with_the_restic_that_writes() -> None:
    """BACKUP-055 AC5: one restic version on both sides of the bucket.

    The nodes install the static binary at `backup.r2.restic_version`; the
    watcher runs the `restic/restic` image. Renovate tracks only the image, so a
    bump there alone turns this red instead of shipping a reader newer than
    every writer.
    """
    from toolkit.scripts.sync_k8s_images import IMAGE_SOURCES

    image = COMMON["backup"]["watcher"]["image"]
    name, tag = image.rsplit(":", 1)
    assert name == "restic/restic"
    assert tag == COMMON["backup"]["r2"]["restic_version"]
    assert "backup.watcher.image" in IMAGE_SOURCES
    kustomization = yaml.safe_load((REPO / "infra/k8s/base/kustomization.yaml").read_text())
    assert {"name": name, "newTag": tag} in kustomization["images"]


def test_every_node_carries_its_declared_repository_id() -> None:
    """BACKUP-058 AC5/AC6: the id column comes from `backup.r2.repository_ids`.

    A restic repository id is 64 hex characters, new for every `init` and fixed
    otherwise, so a declared id pins one history. Every node in `backup.sources`
    must have one: the probe treats an undeclared node as unhealthy.
    """
    rows = _rows(render_watcher_targets(COMMON))
    declared = COMMON["backup"]["r2"]["repository_ids"]
    assert set(declared) == set(COMMON["backup"]["sources"])
    for node, row in rows.items():
        assert row[1] == declared[node], node
        assert len(row[1]) == 64 and all(c in "0123456789abcdef" for c in row[1]), node


def test_an_undeclared_node_renders_the_dash_token() -> None:
    # The probe reads a fixed column, so a missing id must still occupy it:
    # otherwise the first source would be read as the id and the rest shift.
    mutated = yaml.safe_load(yaml.safe_dump(COMMON))
    del mutated["backup"]["r2"]["repository_ids"]["rpi3"]
    rows = _rows(render_watcher_targets(mutated))
    assert rows["rpi3"][1] == "-"
    assert rows["rpi3"][5:] == sorted(COMMON["backup"]["sources"]["rpi3"])


def _networking_entry(config: dict, node: str) -> dict:
    networking = config["networking"]
    return networking["nodes"][node] if node in networking.get("nodes", {}) else networking[node]


def test_every_node_carries_its_tailscale_ip_probe_port_and_class() -> None:
    """BACKUP-032 AC4: what the probe needs to tell "off" from "up and not shipping".

    The IP and the ADR-028 class come from `networking.*`, the port from
    `backup.watcher`. Read here from common.yaml, never retyped, so a node that
    moves address or class moves its watcher row with it.
    """
    rows = _rows(render_watcher_targets(COMMON))
    port = str(COMMON["backup"]["watcher"]["reachability_port"])
    for node, row in rows.items():
        entry = _networking_entry(COMMON, node)
        assert row[2:5] == [entry["tailscale_ip"], port, entry["location"]], node
    assert {row[4] for row in rows.values()} == {"always-on", "on-demand"}


def test_a_per_node_port_overrides_the_default() -> None:
    mutated = yaml.safe_load(yaml.safe_dump(COMMON))
    mutated["backup"]["watcher"]["reachability_ports"] = {"rpi4": 61208}
    rows = _rows(render_watcher_targets(mutated))
    assert rows["rpi4"][3] == "61208"
    assert rows["beelink"][3] == str(COMMON["backup"]["watcher"]["reachability_port"])


@pytest.mark.parametrize("field", ["tailscale_ip", "location"])
def test_a_node_without_an_address_or_a_class_refuses_to_render(field) -> None:
    """Fail closed. A row with no class is a node the freshness rule never sees,
    and a row with no address is one the probe always reports off: both silent."""
    mutated = yaml.safe_load(yaml.safe_dump(COMMON))
    del _networking_entry(mutated, "rpi4")[field]
    with pytest.raises(ValueError, match=f"rpi4.*{field}"):
        render_watcher_targets(mutated)
