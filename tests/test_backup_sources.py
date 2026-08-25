"""Unit tests for the backup source allow-list — BACKUP-044.

Pure SSOT assertions: NO SSH, no live node, no restic. Runs under ``make test``.

``roles/backup`` enumerated every Docker volume and subtracted an exclude list.
Measuring the fleet for #449 showed why that cannot work: on the Beelink, Gitea
is a **bind mount** and so is MinIO, while ``docker volume ls`` returns only
buildx caches and the runner toolcache. Pointed at that node, the old model
archives rebuildable junk, misses both services, and reports success. #1092's
AC3 inverts it to an allow-list; this file guards the declaration side.

The schema's rule is *declare the name we control, resolve the path at run time*,
which is why there are three source types rather than one path field. A literal
``/var/lib/docker/volumes/...`` belongs to Docker (``data-root`` is configurable)
and a PVC's on-disk path embeds a UUID that a recreated claim invalidates in
silence — both are paths another system owns, and declaring them is declaring
something that expires without warning.

**What is NOT here**, and it is the half that catches a real omission: a stateful
path that exists on disk on a covered node and is absent from this list. That
needs a live node, so it belongs in ``tests/infra/`` behind ``require_vpn``. AC6
is not closed by this file — an allow-list that only validates what it declares
cannot report what it forgot.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

COMMON_YAML = Path(__file__).parent.parent / "infra" / "config" / "values" / "common.yaml"


@pytest.fixture(scope="module")
def common() -> dict[str, Any]:
    return yaml.safe_load(COMMON_YAML.read_text())


@pytest.fixture(scope="module")
def hosts(common: dict[str, Any]) -> dict[str, dict[str, Any]]:
    net = common["networking"]
    flat: dict[str, dict[str, Any]] = dict(net["nodes"])
    # See tests/test_node_location_axis.py for why this tuple is hand-maintained
    # and why that is the defect SSOT-015 (#1182) tracks.
    for key in ("vps", "aws", "gcp"):
        if key in net:
            flat[key] = net[key]
    return flat

# The four nodes BACKUP-044 covers, from the ratified tiers (#452). Not the whole
# fleet: ace1/ace2/jetson hold no ratified Tier 1 or Tier 2 state.
COVERED_NODES = {"beelink", "rpi3", "rpi4", "vps"}

# Exactly one of these identifies a source, and which one is present IS the type.
# An explicit `type:` field would be a second source of truth inside every entry,
# always derivable from the rest — the redundancy this repo's SSOT rules exist to
# remove.
SOURCE_TYPES = {"path", "volume", "pvc"}


class TestBackupSources:
    """The allow-list: complete, well-formed, and naming things we control.

    The half NOT here is the one that catches an omission — a stateful path that
    exists on disk on a covered node and is absent from this list. That needs a
    live node, so it belongs in tests/infra/ behind require_vpn. AC6 is not
    closed by this class: an allow-list that only validates what it declares
    cannot report what it forgot.
    """

    @pytest.fixture(scope="module")
    def sources(self, common: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return common["backup"]["sources"]

    def test_all_ratified_nodes_are_covered(self, sources: dict[str, Any]) -> None:
        missing = sorted(COVERED_NODES - set(sources))
        assert not missing, (
            f"nodes holding ratified Tier 1/2 state with no declared source: {missing}. "
            "Measured 2026-08-15, one node of seven had any backup at all and its copy "
            "never left that node (#449)."
        )

    def test_source_nodes_exist_in_the_registry(
        self, sources: dict[str, Any], hosts: dict[str, dict[str, Any]]
    ) -> None:
        unknown = sorted(set(sources) - set(hosts))
        assert not unknown, f"backup.sources names hosts absent from the node registry: {unknown}"

    def test_each_source_declares_exactly_one_type(self, sources: dict[str, Any]) -> None:
        """The schema's central invariant.

        Zero types is an unusable entry. Two is ambiguous — and worse, it is the
        shape a half-finished migration between types leaves behind, which would
        otherwise sit there backing up whichever key the implementation happened
        to check first.
        """
        bad: list[str] = []
        for node, entries in sources.items():
            for name, entry in entries.items():
                found = SOURCE_TYPES & set(entry)
                if len(found) != 1:
                    bad.append(f"{node}.{name} declares {sorted(found) or 'none'}")
        assert not bad, f"every source needs exactly one of {sorted(SOURCE_TYPES)}: {bad}"

    def test_paths_are_absolute_and_names_are_not_paths(self, sources: dict[str, Any]) -> None:
        """A `volume:` holding a path means someone resolved it by hand.

        That is the failure this schema exists to prevent: a literal
        /var/lib/docker/volumes/... is Docker's to move, and a PVC path embeds a
        UUID that a recreated claim invalidates silently.
        """
        bad: list[str] = []
        for node, entries in sources.items():
            for name, entry in entries.items():
                if "path" in entry and not str(entry["path"]).startswith("/"):
                    bad.append(f"{node}.{name} path is not absolute: {entry['path']!r}")
                if "volume" in entry and "/" in str(entry["volume"]):
                    bad.append(f"{node}.{name} volume looks like a resolved path: {entry['volume']!r}")
                if "pvc" in entry and set(entry["pvc"]) != {"namespace", "claim"}:
                    bad.append(f"{node}.{name} pvc needs exactly namespace+claim: {entry['pvc']!r}")
        assert not bad, f"malformed sources: {bad}"

    def test_service_keys_are_shell_identifiers(self, sources: dict[str, Any]) -> None:
        """A service key becomes a bash VARIABLE NAME, so its charset is not cosmetic.

        `node-backup-capture.sh.j2` interpolates the key straight into
        `SRC_DIR_{{ service }}` (lines 65, 81, 84, 89, 99, 112). A key that is
        not a valid shell identifier — `uptime-kuma`, or anything with a space —
        renders a script that Jinja accepts and bash rejects, so the failure
        moves from apply time to run time on the node.

        Found by the BACKUP-044 adversarial review, which rendered the template
        with a key containing a space and got no StrictUndefined error: the
        schema had no charset invariant, and every current key happened to be
        clean. "Happens to be correct" is the state this file exists to convert
        into "cannot be otherwise".

        The failure is loud when it comes (`set -e`), which is why this is a
        guard against a future edit rather than a fix for a live defect.
        """
        bad = [
            f"{node}.{name}"
            for node, entries in sources.items()
            for name in entries
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name))
        ]
        assert not bad, (
            f"backup.sources service keys must be valid shell identifiers: {bad}. "
            "The key is interpolated into a bash variable name (SRC_DIR_<key>), so a "
            "hyphen or a space renders a capture script that only fails on the node. "
            "Rename the key — the declared name is ours to choose, unlike the path."
        )

    def test_rpi3_names_the_live_volume_not_the_orphan(self, sources: dict[str, Any]) -> None:
        """#1092 instance 1 — the orphan is the larger, more canonical-looking one."""
        assert sources["rpi3"]["uptime_kuma"]["volume"] == "uptime_kuma_data", (
            "rpi3's Uptime Kuma source must name uptime_kuma_data. The orphan "
            "uptime-kuma_uptime_kuma_data is 26M against the live 22M and frozen since "
            "2026-03-28; backing it up would capture healthy-looking data the service "
            "does not read, and would pass any check asserting a non-empty backup exists."
        )

    def test_live_sqlite_databases_are_declared(self, sources: dict[str, Any]) -> None:
        """Every one of these was measured with a WAL larger and fresher than the db.

        headscale's was 1.35MB against a 118KB database and eight hours newer, so a
        file copy would have captured under 8% of the state while looking valid.
        """
        for node, name in (("beelink", "gitea"), ("rpi3", "uptime_kuma"),
                           ("rpi4", "pihole"), ("vps", "headscale")):
            assert sources[node][name].get("sqlite"), (
                f"{node}.{name} holds a live SQLite database but declares no `sqlite` key, "
                "so the capture step would copy the file instead of snapshotting it."
            )


class TestPvcSources:
    """The PVC source type — BACKUP-046 (#1111) taken through this pipeline.

    Authelia and n8n are Kubernetes PVCs, but `local-path` puts them on the
    VPS's own disk, so the node-path pipeline reaches them and no in-cluster job
    is needed. That is what retires the prod `pvc-backup` CronJob, which copied
    them to MinIO INSIDE the same cluster — a backup that burns with the thing
    it protects — and downloaded `mc` unpinned from the internet on every run.
    """

    # Derived from the module's existing root constant rather than a second
    # `Path(__file__)` walk — one definition of where the repo is. `.resolve()`
    # first: COMMON_YAML is built from a relative `__file__`, so without it this
    # only lands on the right file when pytest happens to run from the repo root.
    CAPTURE = (
        COMMON_YAML.resolve().parents[3]
        / "infra/ansible/roles/node_backup/templates/node-backup-capture.sh.j2"
    )

    @pytest.fixture(scope="module")
    def sources(self, common: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return common["backup"]["sources"]

    def test_the_path_is_resolved_at_capture_time_never_hardcoded(self) -> None:
        """`local-path` embeds the claim's UID, and a recreated PVC changes it.

        Measured 2026-08-22 against prod:

            n8n-data -> /var/lib/rancher/k3s/storage/pvc-c9613645-..._kubelab_n8n-data

        Hardcode that and a recreated claim leaves the old directory on disk,
        looking healthy, while the backup keeps archiving it and reporting
        success. That is the silent failure this whole pipeline exists to end,
        so the resolution has to happen on the node at capture time.
        """
        script = self.CAPTURE.read_text(encoding="utf-8")
        assert "kubectl get pv" in script, (
            "the capture script no longer resolves PVC paths from the cluster"
        )
        assert "/var/lib/rancher/k3s/storage/pvc-" not in script, (
            "a resolved local-path directory is hardcoded in the capture script; "
            "it embeds a claim UID and dies silently when the PVC is recreated"
        )

    def test_a_missing_claim_fails_the_capture_loudly(self) -> None:
        """An unresolvable PVC must stop the run, not stage an empty directory.

        `set -e` does not cover it: `kubectl` returning nothing is a success with
        empty output, so without this check the script would `cd` into an empty
        string and either fail three lines later for an unrelated-looking reason
        or, worse, capture the wrong thing.
        """
        script = self.CAPTURE.read_text(encoding="utf-8")
        assert "refusing to ship a backup that silently omits it" in script, (
            "the capture script no longer refuses when a declared PVC resolves to "
            "nothing — a claim that was renamed or deleted would be skipped in "
            "silence and the snapshot would look complete"
        )

    def test_the_resolver_filters_on_namespace_and_claim(self) -> None:
        """A bare claim name is ambiguous across namespaces.

        `n8n-data` in `kubelab` and `n8n-data` in some future namespace are
        different volumes; matching on the name alone would pick whichever the
        API listed first.
        """
        script = self.CAPTURE.read_text(encoding="utf-8")
        assert "claimRef.namespace" in script, "the resolver ignores the namespace"
        assert "src.pvc.claim" in script, "the resolver does not filter on the claim name"

    def test_n8n_is_captured_with_sqlite_backup_not_a_file_copy(self, sources: dict[str, Any]) -> None:
        """The measurement that makes this non-negotiable.

        2026-08-22, live: `database.sqlite` is 892 KB and its `-wal` is **4.1 MB**.
        A file copy would omit four times more committed data than it copied, and
        the result would restore cleanly — as a database missing most of its
        recent history.
        """
        assert sources["vps"]["n8n"].get("sqlite") == "database.sqlite", (
            "n8n's source must name its SQLite database so capture uses "
            "`sqlite3 .backup`; a plain copy loses whatever is in the WAL"
        )

    def test_the_retired_and_deferred_pvcs_stay_out(self, sources: dict[str, Any]) -> None:
        """Absence here is a decision, and each one has a different reason.

        Left as a test so re-adding one is deliberate rather than incidental:
        postgres was measured EMPTY (0 tables) and joins the day something
        writes to it — with `pg_dump`, a different mechanism; grafana's
        dashboards belong in git; crowdsec's decisions regenerate; minio is the
        destination being retired, so backing it up would be circular.
        """
        declared = set(sources["vps"])
        for name in ("postgres", "grafana", "crowdsec", "minio", "loki"):
            assert name not in declared, (
                f"{name} was added to the VPS backup sources. That may be right — "
                f"postgres in particular joins the moment it stops being empty — "
                f"but it needs its own reasoning and, for postgres, a capture "
                f"mechanism that is not `sqlite3 .backup`."
            )
