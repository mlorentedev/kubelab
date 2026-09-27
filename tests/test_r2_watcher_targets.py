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

from toolkit.features.backup_destination import WATCHER_TARGETS_PATH, render_watcher_targets

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())


def _rows(text: str) -> dict[str, list[str]]:
    rows = {}
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            node, repository, *services = line.split()
            rows[node] = [repository, *services]
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
        assert sorted(rows[node][1:]) == sorted(declared), node


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
