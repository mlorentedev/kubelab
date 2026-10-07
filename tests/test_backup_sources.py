"""Unit tests for the backup source allow-list — BACKUP-044.

Pure SSOT assertions: NO SSH, no live node, no restic. Runs under ``make test``.

``roles/backup`` enumerated every Docker volume and subtracted an exclude list.
Measuring the fleet for #449 showed why that cannot work: on the Beelink, Gitea
is a **bind mount**, as was the object store OPS-023 later retired, while
``docker volume ls`` returns only buildx caches and the runner toolcache.
Pointed at that node, the old model archives rebuildable junk, misses both
services, and reports success. #1092's
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


# A file under a source is rendered inside both quote styles of the capture
# script (`".backup '$STAGING/<db>'"`), so a quote, `$` or space in it is a broken
# or injected command, not an odd name.
_FILE_UNDER_SOURCE = re.compile(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*")


def _file_rules(entry: dict[str, Any]) -> list[str]:
    """What is wrong with an entry's `sqlite` and `exclude`, both paths under the source."""
    bad: list[str] = []
    dbs = entry.get("sqlite")
    if dbs is not None:
        listed = [dbs] if isinstance(dbs, str) else dbs
        if not isinstance(listed, list) or not listed or len(set(map(str, listed))) != len(listed):
            bad.append(f"sqlite must be one path or a non-empty list of distinct paths: {dbs!r}")
            listed = []
    else:
        listed = []
    excluded = entry.get("exclude") or {}
    if not isinstance(excluded, dict):
        return [*bad, f"exclude must map each path to its ruling: {excluded!r}"]
    for path in [*listed, *excluded]:
        text = str(path)
        if not _FILE_UNDER_SOURCE.fullmatch(text) or ".." in text.split("/"):
            bad.append(f"{text!r} is not a plain relative path under the source")
    for path, ruling in excluded.items():
        if path in listed:
            bad.append(f"{path!r} is declared as a database and excluded")
        # The same ruling backup.excluded asks of a whole volume: only tier 3,
        # rebuilt from upstream, may be left out, and the reason is written down.
        if not isinstance(ruling, dict) or ruling.get("tier") != 3 or not str(ruling.get("reason") or "").strip():
            bad.append(f"exclude.{path} needs a reason and tier: 3, got {ruling!r}")
    return bad


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

    def test_databases_and_exclusions_are_plain_paths_under_the_source(self, sources: dict[str, Any]) -> None:
        bad = [
            f"{node}.{name}: {problem}"
            for node, entries in sources.items()
            for name, entry in entries.items()
            for problem in _file_rules(entry)
        ]
        assert not bad, bad

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
        for node, name in (("beelink", "gitea"), ("rpi3", "uptime_kuma"), ("rpi4", "pihole"), ("vps", "headscale")):
            assert sources[node][name].get("sqlite"), (
                f"{node}.{name} holds a live SQLite database but declares no `sqlite` key, "
                "so the capture step would copy the file instead of snapshotting it."
            )


class TestPvcSources:
    """The PVC source type — BACKUP-046 (#1111) taken through this pipeline.

    Authelia and n8n are Kubernetes PVCs, but `local-path` puts them on the
    VPS's own disk, so the node-path pipeline reaches them and no in-cluster job
    is needed. That is what retired the prod `pvc-backup` CronJob, which copied
    them to a bucket INSIDE the same cluster — a backup that burns with the
    thing it protects — and downloaded its client unpinned on every run.
    """

    # Derived from the module's existing root constant rather than a second
    # `Path(__file__)` walk — one definition of where the repo is. `.resolve()`
    # first: COMMON_YAML is built from a relative `__file__`, so without it this
    # only lands on the right file when pytest happens to run from the repo root.
    CAPTURE = COMMON_YAML.resolve().parents[3] / "infra/ansible/roles/node_backup/templates/node-backup-capture.sh.j2"

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
        assert "kubectl get pv" in script, "the capture script no longer resolves PVC paths from the cluster"
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

    def test_postgres_is_captured_by_logical_dump(self, sources: dict[str, Any]) -> None:
        """BACKUP-046 (#1111): the board's database, by `pg_dumpall`, never by file copy.

        Excluded on 2026-08-22 as empty and unbacked until 2026-10-01 while Vikunja
        wrote to it. The claims that stay out are ruled in `backup.excluded.vps`,
        where tests/test_backup_pvc_coverage.py holds them to tier 3.
        """
        pg = sources["vps"]["postgres"]
        assert pg["pvc"] == {"namespace": "kubelab", "claim": "postgres-data"}
        assert pg["pg_dumpall"] == {"deployment": "postgres", "container": "postgres"}

    def test_pg_dumpall_is_a_capture_method_for_a_claim(self, sources: dict[str, Any]) -> None:
        """Like `sqlite`, a method on top of the source type, and exclusive with it.

        It needs `pvc`, because the dump runs inside the workload that owns the
        claim. It cannot sit beside `sqlite`: one source is one database engine.
        """
        bad: list[str] = []
        for node, entries in sources.items():
            for name, entry in entries.items():
                if "pg_dumpall" not in entry:
                    continue
                if "pvc" not in entry:
                    bad.append(f"{node}.{name}: pg_dumpall without pvc")
                if "sqlite" in entry:
                    bad.append(f"{node}.{name}: pg_dumpall and sqlite together")
                if set(entry["pg_dumpall"]) != {"deployment", "container"}:
                    bad.append(f"{node}.{name}: pg_dumpall needs exactly deployment+container")
                # Both are rendered unquoted into the capture's shell script.
                for key, value in entry["pg_dumpall"].items():
                    if not re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", str(value)):
                        bad.append(f"{node}.{name}: pg_dumpall.{key} {value!r} is not a Kubernetes name")
        assert not bad, bad


@pytest.mark.parametrize(
    "entry",
    [
        {"sqlite": []},
        {"sqlite": ["a.db", "a.db"]},
        {"sqlite": "/abs/a.db"},
        {"sqlite": "../a.db"},
        {"sqlite": "it's.db"},
        {"sqlite": ["a.db", "b c.db"]},
        {"exclude": ["cache"]},
        {"exclude": {"cache": {"reason": "models", "tier": 2}}},
        {"exclude": {"cache": {"tier": 3}}},
        {"exclude": {"$HOME": {"reason": "x", "tier": 3}}},
        {"sqlite": "webui.db", "exclude": {"webui.db": {"reason": "x", "tier": 3}}},
    ],
)
def test_a_malformed_file_declaration_is_refused(entry: dict[str, Any]) -> None:
    assert _file_rules(entry)


def test_a_well_formed_file_declaration_passes() -> None:
    entry = {"sqlite": ["state.db", "cron/executions.db"], "exclude": {"cache": {"reason": "models", "tier": 3}}}
    assert _file_rules(entry) == []
    assert _file_rules({"sqlite": "gitea/gitea.db"}) == []
