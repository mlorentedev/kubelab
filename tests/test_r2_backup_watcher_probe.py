"""The R2 watcher's probe: what it reports, and that it never goes silent (BACKUP-055 AC1, AC3).

The previous watcher was `echo healthy:1`. It could only fail by not running, so
the alert above it measured the CronJob, not the backups. These tests run the
real `probe.sh` under `sh` against a fake `restic` on PATH and read what it
prints, which is exactly what Vector ships to Loki.

Two properties matter more than any single check:

- **One bad node is never masked.** The fleet line is healthy only if every
  node is, whatever order the nodes are probed in.
- **Every exit path reports.** A restic that crashes, hangs, or a pod started
  without its Secret must still end in `r2_backup_health` `healthy:0`. A probe
  that can exit without a line hands the decision to the rule's 24h noData
  window, a day late.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time

import shutil

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
PROBE = REPO / "infra/k8s/base/services/r2-backup-watcher/probe.sh"
STAGING = "/opt/node-backup/staging"
PREFIX = "s3:https://example.r2.cloudflarestorage.com/kubelab-backups"

# Stands in for restic. Behaviour per repository comes from files in $FAKE_DIR,
# named after the repository's last path segment:
#   <repo>.fail   exit 1 with that file's text on stderr (no repo, bad password)
#   <repo>.crash  exit 137, as if OOM-killed
#   <repo>.hang   sleep far past any timeout
#   <repo>.refuse retry a rejected request forever, printing restic's retry
#                 line each time (R2's answer to a bad credential, #1939)
#   <repo>.snaps  what `snapshots --json` prints (default: one snapshot)
#   <repo>.ls     what `ls latest <dir>` prints
#   <repo>.id     the repository id `cat config --json` reports (BACKUP-058)
#   <repo>.size   the `total_size` `stats --mode raw-data --json` reports
#   <repo>.nostats `stats` alone fails, the rest of the repository reads fine
#   <repo>.nototal `stats` exits 0 and its JSON has no `total_size`
# Any call without --no-lock is refused the way the read-only token refuses it
# (PutObject AccessDenied on the lock) and logged as `locked <repo>`.
FAKE_RESTIC = r"""#!/bin/sh
ORIG_ARGS="$*"
repo=""; cmd=""
while [ $# -gt 0 ]; do
  case "$1" in
    -r) repo="$2"; shift ;;
    snapshots|ls|cat|stats) [ -z "$cmd" ] && cmd="$1" ;;
  esac
  shift
done
name="${repo##*/}"
echo "$cmd $name" >> "$FAKE_DIR/calls"
case " $ORIG_ARGS " in
  *" --no-lock "*) ;;
  *) echo "locked $name" >> "$FAKE_DIR/calls"
     echo "unable to create lock in backend: client.PutObject: Access Denied" >&2; exit 1 ;;
esac
[ -f "$FAKE_DIR/$name.fail" ] && { cat "$FAKE_DIR/$name.fail" >&2; exit 1; }
[ -f "$FAKE_DIR/$name.crash" ] && exit 137
[ -f "$FAKE_DIR/$name.hang" ] && exec sleep 30
if [ -f "$FAKE_DIR/$name.refuse" ]; then
  while :; do
    echo "Stat(<config/>) returned error, retrying after 875.524205ms: Stat: Unauthorized" >&2
    sleep 0.2
  done
fi
case "$cmd" in
  snapshots)
    if [ -f "$FAKE_DIR/$name.snaps" ]; then cat "$FAKE_DIR/$name.snaps"
    else echo '[{"time":"2026-09-26T00:00:00Z","id":"abc","short_id":"abc12345"}]'; fi ;;
  ls) cat "$FAKE_DIR/$name.ls" ;;
  cat) printf '{"version":2,"id":"%s","chunker_polynomial":"3dea92648f6e83"}\n' "$(cat "$FAKE_DIR/$name.id")" ;;
  stats)
    [ -f "$FAKE_DIR/$name.nostats" ] && { echo "Load(<index/0a1b>) failed: timeout" >&2; exit 1; }
    [ -f "$FAKE_DIR/$name.nototal" ] && { echo '{"total_blob_count":42,"snapshots_count":3}'; exit 0; }
    case " $ORIG_ARGS " in *" --mode raw-data "*) ;; *) echo "wrong stats mode: $ORIG_ARGS" >&2; exit 2 ;; esac
    printf '{"total_size":%s,"total_uncompressed_size":%s,"compression_ratio":1.9,"total_blob_count":42,"snapshots_count":3}\n' \
      "$(cat "$FAKE_DIR/$name.size")" "$(( $(cat "$FAKE_DIR/$name.size") * 2 ))" ;;
esac
"""


# Stands in for busybox `nc -z -w <s> <address> <port>` (BACKUP-032). Behaviour
# per address from files in $FAKE_DIR: <address>.down refuses (exit 1),
# <address>.hang never answers. Otherwise the port is open. Every call is
# logged with its arguments, so a test can read which port was knocked on.
FAKE_NC = r"""#!/bin/sh
echo "nc $*" >> "$FAKE_DIR/calls"
for last; do :; done
port="$last"
address=""
for arg; do [ "$arg" = "$port" ] && break; address="$arg"; done
[ -f "$FAKE_DIR/$address.down" ] && exit 1
[ -f "$FAKE_DIR/$address.hang" ] && exec sleep 30
exit 0
"""

# Repository ids as `restic cat config` reports them: new for every `init`,
# fixed otherwise. The targets file declares the id each node must still have.
IDS = {"rpi3": "1" * 64, "kubelab-vps": "2" * 64}
# The probe's clock, pinned so an age is an exact number. The fake restic's
# default snapshot is stamped 2026-09-26T00:00:00Z, so every default age is 6 h.
SNAPSHOT_TIME = "2026-09-26T00:00:00Z"
SNAPSHOT_EPOCH = 1_790_380_800
NOW = SNAPSHOT_EPOCH + 6 * 3600
# Where the probe knocks (BACKUP-032). Documentation addresses (RFC 5737): the
# fake `nc` answers for them from files, and nothing real is ever contacted.
ADDRESSES = {"rpi3": "192.0.2.6", "vps": "192.0.2.2"}
# What `stats --mode raw-data` reports as `total_size`: the stored, compressed
# bytes of every blob the snapshots reference (BACKUP-057 Q3).
SIZES = {"rpi3": 123_456_789, "kubelab-vps": 2_345_678_901}


def _listing(*services: str, sentinel: bool = True) -> str:
    lines = [
        "snapshot abc12345 of [/opt/node-backup/staging] at 2026-09-26 00:00:00 filtered by [/opt/node-backup/staging]:"
    ]
    lines += [f"{STAGING}/{s}" for s in services]
    if sentinel:
        lines.append(f"{STAGING}/.capture-complete")
    return "\n".join(lines) + "\n"


# The image runs busybox `sh`, the host usually dash: run every case under both,
# so a bashism or a dash-only behaviour cannot pass here and fail in the pod.
SHELLS = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])


@pytest.fixture(params=SHELLS, ids=lambda s: " ".join(s))
def fleet(tmp_path: pathlib.Path, request):
    """A two-node fleet whose repositories are healthy until a test breaks one."""
    fake = tmp_path / "fake"
    fake.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    restic = bin_dir / "restic"
    restic.write_text(FAKE_RESTIC)
    restic.chmod(0o755)
    nc = bin_dir / "nc"
    nc.write_text(FAKE_NC)
    nc.chmod(0o755)
    targets = tmp_path / "targets.txt"
    targets.write_text(
        "# header comment\n"
        f"rpi3 {PREFIX}/rpi3 {IDS['rpi3']} {ADDRESSES['rpi3']} 22 always-on uptime_kuma\n"
        f"vps {PREFIX}/kubelab-vps {IDS['kubelab-vps']} {ADDRESSES['vps']} 22 always-on authelia n8n\n"
    )
    for name, repository_id in IDS.items():
        (fake / f"{name}.id").write_text(f"{repository_id}\n")
        (fake / f"{name}.size").write_text(f"{SIZES[name]}\n")
    (fake / "rpi3.ls").write_text(_listing("uptime_kuma"))
    (fake / "kubelab-vps.ls").write_text(_listing("authelia", "n8n"))
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "WATCHER_TARGETS": str(targets),
        "STAGING_DIR": STAGING,
        "SENTINEL": ".capture-complete",
        "RESTIC_TIMEOUT": "2",
        "REACH_TIMEOUT": "1",
        # By path: Ubuntu's busybox `sh` prefers its own `nc` applet to PATH.
        "NC": str(nc),
        "PROBE_NOW": str(NOW),
        "RESTIC_PASSWORD": "not-a-real-value-fixture",
        "AWS_ACCESS_KEY_ID": "not-a-real-value-fixture",
        "AWS_SECRET_ACCESS_KEY": "not-a-real-value-fixture",
        "PROBE_SHELL": " ".join(request.param),
    }
    return fake, targets, env


def _run(env: dict[str, str]) -> tuple[int, list[dict], list[dict]]:
    shell = env.get("PROBE_SHELL", "sh").split()
    proc = subprocess.run([*shell, str(PROBE)], env=env, capture_output=True, text=True, timeout=60)
    records = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    nodes = [r for r in records if r["metric"] == "r2_backup_node"]
    fleet_lines = [r for r in records if r["metric"] == "r2_backup_health"]
    assert len(fleet_lines) == 1, f"exactly one fleet line, got {proc.stdout!r} / {proc.stderr!r}"
    assert all(r["namespace"] == "kubelab" for r in records)
    return proc.returncode, nodes, fleet_lines


def _node(nodes: list[dict], name: str) -> dict:
    return next(n for n in nodes if n["node"] == name)


def test_a_healthy_fleet_reports_every_node_and_a_healthy_fleet(fleet) -> None:
    _, _, env = fleet
    rc, nodes, (summary,) = _run(env)
    assert rc == 0
    assert {n["node"] for n in nodes} == {"rpi3", "vps"}
    for n in nodes:
        assert n == {**n, "readable": 1, "snapshots": 1, "missing": [], "sentinel": 1, "healthy": 1}
    assert _node(nodes, "rpi3")["repository_id"] == IDS["rpi3"]
    assert _node(nodes, "vps")["repository_id"] == IDS["kubelab-vps"]
    assert summary["healthy"] == 1
    assert summary["nodes"] == 2 and summary["unhealthy"] == 0


def test_the_probe_lists_one_directory_not_the_whole_tree(fleet) -> None:
    # A recursive `ls` took 92 s on the Beelink (R3); the probe must not recurse.
    fake, _, env = fleet
    _run(env)
    assert "ls kubelab-vps" in (fake / "calls").read_text()
    proc = subprocess.run(["grep", "-c", "--", "--recursive", str(PROBE)], capture_output=True, text=True)
    assert proc.stdout.strip() == "0"


def test_the_probe_never_takes_a_lock(fleet) -> None:
    """The token is read-only, so every restic call must skip the lock.

    Judged by the calls the probe makes, not by grepping it: a direct `restic`
    call added outside `restic_read`, even one whose failure is swallowed, shows
    up here as `locked <repo>`.
    """
    fake, _, env = fleet
    rc, _, (summary,) = _run(env)
    calls = (fake / "calls").read_text().splitlines()
    assert calls, "the probe made no restic call at all"
    assert not [c for c in calls if c.startswith("locked ")], calls
    assert rc == 0 and summary["healthy"] == 1


@pytest.mark.parametrize(
    ("breakage", "field", "value"),
    [
        ("missing source", "missing", ["n8n"]),
        ("no repository", "readable", 0),
        ("wrong password", "readable", 0),
        ("zero snapshots", "snapshots", 0),
        ("missing sentinel", "sentinel", 0),
        ("restic crashes", "healthy", 0),
        ("restic hangs", "healthy", 0),
        # BACKUP-058: a repository deleted and re-created, or swapped for another,
        # opens and holds snapshots like the real one. Only its id tells them apart.
        ("repository replaced", "reason", "repository id changed"),
        ("repository id not declared", "reason", "repository id not declared"),
    ],
)
def test_each_breakage_fails_its_node_and_the_fleet(fleet, breakage, field, value) -> None:
    fake, _, env = fleet
    vps = "kubelab-vps"
    if breakage == "missing source":
        (fake / f"{vps}.ls").write_text(_listing("authelia"))
    elif breakage == "no repository":
        (fake / f"{vps}.fail").write_text("Fatal: repository does not exist: unable to open config file\n")
    elif breakage == "wrong password":
        (fake / f"{vps}.fail").write_text("Fatal: wrong password or no key found\n")
    elif breakage == "zero snapshots":
        (fake / f"{vps}.snaps").write_text("[]\n")
    elif breakage == "missing sentinel":
        (fake / f"{vps}.ls").write_text(_listing("authelia", "n8n", sentinel=False))
    elif breakage == "restic crashes":
        (fake / f"{vps}.crash").write_text("")
    elif breakage == "restic hangs":
        (fake / f"{vps}.hang").write_text("")
    elif breakage == "repository replaced":
        (fake / f"{vps}.id").write_text("3" * 64 + "\n")
    elif breakage == "repository id not declared":
        targets = pathlib.Path(env["WATCHER_TARGETS"])
        targets.write_text(targets.read_text().replace(IDS[vps], "-"))

    started = time.monotonic()
    rc, nodes, (summary,) = _run(env)
    assert time.monotonic() - started < 20, "a hanging restic must be cut off by RESTIC_TIMEOUT"

    assert rc != 0
    assert _node(nodes, "vps")[field] == value
    assert _node(nodes, "vps")["healthy"] == 0
    if breakage == "repository replaced":
        # The line names the id R2 holds now, so the operator can compare it.
        assert _node(nodes, "vps")["repository_id"] == "3" * 64
    assert _node(nodes, "rpi3")["healthy"] == 1, "one broken node must not fail its neighbours"
    assert summary["healthy"] == 0 and summary["unhealthy"] == 1


def test_a_broken_node_is_not_masked_by_a_healthy_one_after_it(fleet) -> None:
    fake, targets, env = fleet
    # The broken node is probed FIRST and a healthy one last.
    (fake / "rpi3.fail").write_text("Fatal: repository does not exist\n")
    rc, nodes, (summary,) = _run(env)
    assert [n["node"] for n in nodes] == ["rpi3", "vps"]
    assert nodes[-1]["healthy"] == 1
    assert summary["healthy"] == 0


@pytest.mark.parametrize("missing", ["RESTIC_PASSWORD", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"])
def test_a_pod_without_its_secret_still_reports_unhealthy(fleet, missing) -> None:
    _, _, env = fleet
    env = {k: v for k, v in env.items() if k != missing}
    rc, nodes, (summary,) = _run(env)
    assert rc != 0
    assert summary["healthy"] == 0
    assert missing in summary["error"]


def test_missing_targets_still_report_unhealthy(fleet) -> None:
    _, targets, env = fleet
    targets.unlink()
    rc, _, (summary,) = _run(env)
    assert rc != 0 and summary["healthy"] == 0


def test_a_last_target_without_a_newline_is_still_probed(fleet) -> None:
    """`read` returns non-zero on a final line with no newline; that node must not vanish.

    Dropping it would print a healthy fleet with one node fewer and rc=0, a false
    green nothing in the output would reveal.
    """
    fake, targets, env = fleet
    targets.write_text(targets.read_text().rstrip("\n"))
    (fake / "kubelab-vps.fail").write_text("Fatal: repository does not exist\n")
    rc, nodes, (summary,) = _run(env)
    assert {n["node"] for n in nodes} == {"rpi3", "vps"}
    assert summary["nodes"] == 2
    assert rc != 0 and summary["healthy"] == 0


def test_an_empty_target_list_is_not_a_healthy_fleet(fleet) -> None:
    # Zero nodes checked is zero evidence, not a pass.
    _, targets, env = fleet
    targets.write_text("# only a header\n")
    rc, _, (summary,) = _run(env)
    assert rc != 0 and summary["healthy"] == 0


def test_a_rejected_credential_is_named_in_the_nodes_reason(fleet) -> None:
    """restic retries R2's 401 for 15 minutes; RESTIC_TIMEOUT ends it, and the reason names the 401.

    The first stderr line is restic's first retry, which carries R2's own
    answer. So `unreadable:` is not empty for a bad credential (#1939).
    """
    fake, _, env = fleet
    (fake / "kubelab-vps.refuse").write_text("")
    started = time.monotonic()
    rc, nodes, (summary,) = _run(env)
    assert time.monotonic() - started < 20, "a refused credential must be cut off by RESTIC_TIMEOUT"
    vps = _node(nodes, "vps")
    assert rc != 0 and vps["healthy"] == 0 and vps["readable"] == 0
    assert "Unauthorized" in vps["reason"], vps["reason"]
    assert _node(nodes, "rpi3")["healthy"] == 1


def test_each_node_and_the_fleet_report_their_raw_size(fleet) -> None:
    """The size decides whether a retention window fits the free tier (BACKUP-057 Q3).

    It is measured on every run, not once: the bucket lock keeps data R days
    past what `forget` would have removed, so the number the decision rests
    on has to keep being checked after the decision.
    """
    _, _, env = fleet
    rc, nodes, (summary,) = _run(env)
    assert rc == 0
    assert _node(nodes, "rpi3")["raw_bytes"] == SIZES["rpi3"]
    assert _node(nodes, "vps")["raw_bytes"] == SIZES["kubelab-vps"]
    assert summary["raw_bytes"] == sum(SIZES.values())


def test_an_unknown_size_is_null_and_never_fails_a_healthy_node(fleet) -> None:
    """`stats` failing says nothing about whether the backup is restorable.

    So the node stays healthy, and its size is `null` rather than 0: a zero
    would read as "fits" to the size rule and to the retention gate. One
    unknown node makes the fleet sum unknown too, for the same reason.
    """
    fake, _, env = fleet
    (fake / "kubelab-vps.nostats").write_text("")
    rc, nodes, (summary,) = _run(env)
    vps = _node(nodes, "vps")
    assert rc == 0 and vps["healthy"] == 1 and summary["healthy"] == 1
    assert vps["raw_bytes"] is None
    assert _node(nodes, "rpi3")["raw_bytes"] == SIZES["rpi3"]
    assert summary["raw_bytes"] is None


@pytest.mark.parametrize(
    ("marker", "reason"),
    [("nostats", "Load(<index/0a1b>) failed: timeout"), ("nototal", "stats returned no total_size")],
)
def test_an_unknown_size_names_its_reason(fleet, marker, reason) -> None:
    """A `null` comes with a `size unknown:` line naming why, including when `stats` itself succeeded."""
    fake, _, env = fleet
    (fake / f"kubelab-vps.{marker}").write_text("")
    shell = env.get("PROBE_SHELL", "sh").split()
    proc = subprocess.run([*shell, str(PROBE)], env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    assert f"r2-backup-watcher: vps: size unknown: {reason}\n" in proc.stderr


def test_an_unreadable_node_has_no_size(fleet) -> None:
    fake, _, env = fleet
    (fake / "kubelab-vps.fail").write_text("Fatal: wrong password or no key found\n")
    _, nodes, (summary,) = _run(env)
    assert _node(nodes, "vps")["raw_bytes"] is None
    assert summary["raw_bytes"] is None


def test_a_probe_that_stops_early_reports_no_fleet_size(fleet) -> None:
    """A partial sum would understate the fleet, which is the one error the size rule must not make."""
    fake, _, env = fleet
    (fake / "kubelab-vps.hang").write_text("")
    # The shell runs its TERM trap once the foreground restic returns, which
    # RESTIC_TIMEOUT bounds: the same order a pod's activeDeadlineSeconds sees.
    env = {**env, "RESTIC_TIMEOUT": "4"}
    proc = subprocess.Popen([*env["PROBE_SHELL"].split(), str(PROBE)], env=env, stdout=subprocess.PIPE, text=True)
    time.sleep(1)
    proc.terminate()
    out, _ = proc.communicate(timeout=20)
    (summary,) = [json.loads(line) for line in out.splitlines() if '"r2_backup_health"' in line]
    assert summary["healthy"] == 0
    assert summary["raw_bytes"] is None


# --- BACKUP-032: snapshot age, reachability and class -----------------------


def _snaps(*times: str) -> str:
    return "[" + ",".join(f'{{"time":"{t}","id":"x{i}","short_id":"s{i}"}}' for i, t in enumerate(times)) + "]\n"


def test_each_node_reports_its_newest_snapshot_age_reachability_and_class(fleet) -> None:
    _, _, env = fleet
    rc, nodes, (summary,) = _run(env)
    assert rc == 0 and summary["healthy"] == 1
    for n in nodes:
        assert n["newest_snapshot"] == SNAPSHOT_TIME, n
        assert n["snapshot_age_seconds"] == 6 * 3600, n
        assert n["reachable"] == 1, n
        assert n["class"] == "always-on", n


@pytest.mark.parametrize(
    ("stamp", "utc"),
    [
        # What the fleet writes today (measured 2026-10-02): a 9- or 8-digit
        # fraction, and the source node's offset.
        ("2026-09-26T02:00:00.123456789+02:00", "2026-09-26T00:00:00Z"),
        ("2026-09-26T02:00:00.12345678+02:00", "2026-09-26T00:00:00Z"),
        ("2026-09-26T00:00:00.123456789Z", "2026-09-26T00:00:00Z"),
        # Offsets whose hours read as octal in shell arithmetic: `$((08))` is an
        # error in busybox and dash, so a +02:00-only test passes with that bug.
        ("2026-09-25T16:00:00-08:00", "2026-09-26T00:00:00Z"),
        ("2026-09-26T09:30:00+09:30", "2026-09-26T00:00:00Z"),
        ("2026-09-26T00:00:00Z", "2026-09-26T00:00:00Z"),
    ],
)
def test_the_snapshot_time_is_converted_to_utc_from_any_offset(fleet, stamp, utc) -> None:
    fake, _, env = fleet
    (fake / "kubelab-vps.snaps").write_text(_snaps(stamp))
    rc, nodes, _ = _run(env)
    vps = _node(nodes, "vps")
    assert rc == 0 and vps["healthy"] == 1
    assert vps["newest_snapshot"] == utc
    assert vps["snapshot_age_seconds"] == 6 * 3600


def test_the_newest_of_several_snapshots_is_the_one_reported(fleet) -> None:
    """`--latest 1` answers once per path group, so two groups return two snapshots.

    The older one comes first here: a probe that took the first `time` would
    report a stale backup for a node that shipped an hour ago.
    """
    fake, _, env = fleet
    (fake / "kubelab-vps.snaps").write_text(_snaps("2026-09-20T00:00:00Z", "2026-09-26T05:00:00Z"))
    rc, nodes, _ = _run(env)
    vps = _node(nodes, "vps")
    assert vps["newest_snapshot"] == "2026-09-26T05:00:00Z"
    assert vps["snapshot_age_seconds"] == 3600


def test_a_snapshot_list_with_spaces_after_its_colons_still_reads(fleet) -> None:
    """restic prints compact JSON today; a pretty-printed answer is the same answer."""
    fake, _, env = fleet
    (fake / "kubelab-vps.snaps").write_text('[{"time": "2026-09-26T00:00:00Z", "id": "x", "short_id": "s"}]\n')
    _, nodes, _ = _run(env)
    assert _node(nodes, "vps")["snapshot_age_seconds"] == 6 * 3600


@pytest.mark.parametrize("breakage", ["restic fails", "zero snapshots"])
def test_no_snapshot_to_read_is_null_never_a_fresh_looking_age(fleet, breakage) -> None:
    """A `null` age is dropped by the freshness rule's `unwrap`, and the node is
    unhealthy, so the health rule pages instead: never a 0 that reads as fresh."""
    fake, _, env = fleet
    if breakage == "restic fails":
        (fake / "kubelab-vps.fail").write_text("Fatal: wrong password or no key found\n")
    else:
        (fake / "kubelab-vps.snaps").write_text("[]\n")
    rc, nodes, _ = _run(env)
    vps = _node(nodes, "vps")
    assert vps["newest_snapshot"] is None and vps["snapshot_age_seconds"] is None
    assert vps["healthy"] == 0 and rc != 0


def test_an_unparseable_snapshot_time_is_null_and_fails_the_node(fleet) -> None:
    """A time the probe cannot read would leave the freshness rule blind for that
    node with nothing paging, so it fails closed, like an unreadable repository id."""
    fake, _, env = fleet
    (fake / "kubelab-vps.snaps").write_text(_snaps("26/09/2026 00:00"))
    rc, nodes, (summary,) = _run(env)
    vps = _node(nodes, "vps")
    assert vps["newest_snapshot"] is None and vps["snapshot_age_seconds"] is None
    assert vps["healthy"] == 0 and "snapshot time unreadable" in vps["reason"]
    assert summary["healthy"] == 0 and rc != 0


def test_the_probe_knocks_on_each_nodes_declared_port_with_a_timeout(fleet) -> None:
    fake, targets, env = fleet
    targets.write_text(targets.read_text().replace(f"{ADDRESSES['rpi3']} 22 ", f"{ADDRESSES['rpi3']} 2222 "))
    _run(env)
    calls = [c for c in (fake / "calls").read_text().splitlines() if c.startswith("nc ")]
    assert f"nc -z -w 1 {ADDRESSES['rpi3']} 2222" in calls, calls
    assert f"nc -z -w 1 {ADDRESSES['vps']} 22" in calls, calls


def _make_on_demand(targets: pathlib.Path, node: str) -> None:
    lines = targets.read_text().splitlines(keepends=True)
    targets.write_text(
        "".join(ln.replace(" always-on ", " on-demand ") if ln.startswith(f"{node} ") else ln for ln in lines)
    )


def test_an_on_demand_node_that_is_off_stays_healthy(fleet) -> None:
    """Off is that node's normal state (ADR-028): the class is what makes 0 fine."""
    fake, targets, env = fleet
    _make_on_demand(targets, "rpi3")
    (fake / f"{ADDRESSES['rpi3']}.down").write_text("")
    rc, nodes, (summary,) = _run(env)
    rpi3 = _node(nodes, "rpi3")
    assert rpi3["reachable"] == 0 and rpi3["class"] == "on-demand"
    assert rpi3["healthy"] == 1 and summary["healthy"] == 1 and rc == 0


@pytest.mark.parametrize("failure", ["down", "hang"])
def test_an_always_on_node_the_probe_cannot_reach_fails_the_fleet(fleet, failure) -> None:
    """BACKUP-032 AC6: the positive control. An always-on node is never off, so
    `reachable=0` there means the probe is broken (a port, an ACL, the pod's
    route), and a broken probe would read every on-demand node as off forever."""
    fake, _, env = fleet
    (fake / f"{ADDRESSES['vps']}.{failure}").write_text("")
    started = time.monotonic()
    rc, nodes, (summary,) = _run(env)
    assert time.monotonic() - started < 20, "a silent address must be cut off by the timeout"
    vps = _node(nodes, "vps")
    assert vps["reachable"] == 0 and vps["healthy"] == 0
    assert "probe cannot reach an always-on node" in vps["reason"]
    assert _node(nodes, "rpi3")["healthy"] == 1
    assert summary["healthy"] == 0 and summary["unhealthy"] == 1 and rc != 0
