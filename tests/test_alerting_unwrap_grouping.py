"""Every Loki `unwrap` query over a CronJob-sourced container must group by
an identity that survives the CronJob's own pod churn (OBS-018 AC4).

A CronJob makes a new pod per run, and Vector labels every Loki stream with
`pod` (services/vector.yaml). An `unwrap` query with no `by()` clause is
therefore keyed by (pod, ...) rather than by the thing the alert is actually
about: each run starts a fresh series, the previous run's series goes stale
once the LogQL window passes it, and a rule with `noDataState: Alerting`
turns that staleness into a false Resolved/Alerting flap regardless of the
real state being watched. Measured live in staging 2026-08-27: the
`obs015-pvc-unbound-failure` rule produced four simultaneous alerting
instances for one drill PVC, one per disk-watcher pod, none older than the
30m window.

Scope, deliberately narrow: this checks the two static properties a regex can
verify without a cluster — grouping is present, and the specific `.status.phase
== "Bound"` boolean regression (#1377/#1378) has not returned. It does not
re-implement a LogQL parser or prove the rules are semantically correct.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ALERTING_DIR = REPO_ROOT / "infra/k8s/base/services/grafana-alerting"

#: Containers backed by a CronJob (new pod per run), not a long-running
#: Deployment. A small explicit list, same shape as this repo's other
#: registries (SECRET_CATALOG, MIDDLEWARE_CATALOG) — a container added here
#: needs a human decision, not a heuristic guess at its workload kind.
CRONJOB_CONTAINERS = {"disk-watcher", "quota-watcher", "r2-backup-watcher"}

_LAST_OVER_TIME_UNWRAP = re.compile(
    r'\{container="(?P<container>[^"]+)"\}.*?\|\s*unwrap\s+\w+\s*\n\s*\[[^\]]+\]\s*\)(?P<tail>\s*by\s*\([^)]*\))?',
    re.DOTALL,
)


def _rule_files() -> list[pathlib.Path]:
    return sorted(ALERTING_DIR.glob("*.yaml"))


def test_every_cronjob_sourced_unwrap_query_groups_by_something() -> None:
    missing: list[str] = []
    for path in _rule_files():
        text = path.read_text(encoding="utf-8")
        for match in _LAST_OVER_TIME_UNWRAP.finditer(text):
            if match.group("container") in CRONJOB_CONTAINERS and not match.group("tail"):
                missing.append(f"{path.name}: unwrap query over {match.group('container')!r} has no by() clause")
    assert missing == [], "\n".join(missing)


def test_disk_watcher_emitter_never_regresses_to_the_boolean_form() -> None:
    """#1377/#1378: `(.status.phase == "Bound")` yields a JSON boolean, which
    LogQL's `unwrap` cannot parse as a float — the sample is silently dropped
    and `noDataState: Alerting` turns that into a permanent false alarm.
    """
    text = (REPO_ROOT / "infra/k8s/base/services/disk-watcher.yaml").read_text(encoding="utf-8")
    assert '(.status.phase == "Bound")' not in text
    assert 'if .status.phase == "Bound" then 1 else 0 end' in text


def test_cronjob_container_registry_matches_real_cronjobs() -> None:
    """The registry above is read by a human, not derived — this keeps it honest
    against the manifests it claims to describe.
    """
    services_dir = REPO_ROOT / "infra/k8s/base/services"
    for name in CRONJOB_CONTAINERS:
        manifest = services_dir / f"{name}.yaml"
        assert manifest.exists(), f"{name} is declared as a CronJob container but {manifest} does not exist"
        docs = [d for d in yaml.safe_load_all(manifest.read_text(encoding="utf-8")) if d]
        kinds = {d.get("kind") for d in docs}
        assert "CronJob" in kinds, f"{name} is declared as a CronJob container but {manifest} has no CronJob"
