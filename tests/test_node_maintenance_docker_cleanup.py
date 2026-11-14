"""node_maintenance has two implementations of its Docker cleanup — the
Ansible tasks `make maintain` runs, and the shell script the weekly timer
runs — and nothing enforces that they agree. ANSIBLE-046 (#1456) added a
stopped-container prune and an orphaned-buildx-builder warning to close a gap
(months-old `buildx_buildkit_builder-<uuid>` containers, invisible to
`docker buildx ls`, that the existing `docker builder prune` never reached).
This guards that the two implementations still say the same thing.
"""

from __future__ import annotations

import pathlib
import re

import jinja2
import pytest
import yaml
from tests.shells import BASH

REPO = pathlib.Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/node_maintenance"


def _tasks() -> str:
    return (ROLE / "tasks/main.yml").read_text(encoding="utf-8")


def _render_script() -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = lambda v: str(v).lower() in ("true", "yes", "1")
    tpl = (ROLE / "templates/kubelab-maintenance.sh.j2").read_text(encoding="utf-8")
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    return env.from_string(tpl).render({**defaults, "ansible_managed": "am", "inventory_hostname": "kubelab-vps"})


KEEP_STACKS = '--filter "label!=com.docker.compose.project"'


def _container_prunes(text: str) -> list[str]:
    """Each `docker container prune` command line, not the text of its warning."""
    return re.findall(r"docker container prune -[^\n]*", text)


def test_both_implementations_prune_stopped_containers() -> None:
    assert "docker container prune -f" in _tasks()
    assert "docker container prune -f" in _render_script()


@pytest.mark.parametrize("source", ["tasks", "script"])
def test_a_stopped_stack_keeps_its_container_and_so_its_image(source: str) -> None:
    """`image prune -a` spares an image a container still references, stopped or not.
    A stack's units stop with `compose stop`, so their containers outlive a stop,
    and only the container prune could take them, and the image with them. ace2 lost
    its Open WebUI image that way (#2703)."""
    text = _tasks() if source == "tasks" else _render_script()
    prunes = _container_prunes(text)
    assert prunes, f"no container prune found in the {source}"
    for prune in prunes:
        assert KEEP_STACKS in prune, f"{source}: {prune!r} would remove a stopped compose stack"


def test_both_implementations_check_for_orphaned_buildx_builders() -> None:
    assert "buildx_buildkit_builder-" in _tasks()
    assert "buildx_buildkit_builder-" in _render_script()


# --------------------------------------------------------------------------- prune by disk pressure (#3079)
# A daily `prune -a` empties the image store and the build cache whatever the disk
# says, so a CI node starts every morning cold (#3079). A node may opt into pruning
# only what is unused AND only when the filesystem holding Docker passes a threshold;
# below it, only dangling images and build cache go. 0, the default, keeps the daily
# full prune everywhere else.

GATE = "maintenance_docker_prune_above_percent"
BEGIN, END = "# BEGIN docker-prune-gate", "# END docker-prune-gate"


def _gate_block(threshold: int) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = lambda v: str(v).lower() in ("true", "yes", "1")
    tpl = (ROLE / "templates/kubelab-maintenance.sh.j2").read_text(encoding="utf-8")
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    context = {**defaults, "ansible_managed": "am", "inventory_hostname": "kubelab-bee", "group_names": []}
    context[GATE] = threshold
    text = env.from_string(tpl).render(context)
    assert BEGIN in text and END in text, "the prune gate's markers are gone"
    return text[text.index(BEGIN) : text.index(END)]


# Not Docker's default root, so the gate cannot pass by measuring its fallback path.
DOCKER_ROOT = "/srv/docker-root"


def _run_gate(tmp_path: pathlib.Path, threshold: int, df_percent: str, df_rc: int = 0) -> list[str]:
    """Run the rendered gate against stub `docker` and `df`; return docker's argv lines."""
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    (bin_dir / "docker").write_text(
        f'#!/bin/sh\nif [ "$1" = info ]; then echo {DOCKER_ROOT}; exit 0; fi\necho "$*" >> {log}\n',
        encoding="utf-8",
        newline="\n",
    )
    # Any other filesystem reads full, so measuring the wrong one prunes everything
    # and the below-threshold case goes red.
    (bin_dir / "df").write_text(
        f'#!/bin/sh\necho "Use%"\nfor a; do last="$a"; done\n'
        f'if [ "$last" = {DOCKER_ROOT} ]; then echo " {df_percent}%"; else echo " 99%"; fi\nexit {df_rc}\n',
        encoding="utf-8",
        newline="\n",
    )
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    script = tmp_path / "gate.sh"
    # The maintenance script runs under `set -euo pipefail`, so the gate is tested under it too.
    script.write_text("#!/bin/bash\nset -euo pipefail\n" + _gate_block(threshold), encoding="utf-8", newline="\n")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    subprocess.run([BASH, str(script)], check=True, env=env, capture_output=True, text=True, encoding="utf-8")
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _default_for(groups: list[str]) -> int:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    return int(jinja2.Environment().from_string(str(defaults[GATE])).render(group_names=groups))


def test_every_node_but_the_platform_node_keeps_the_daily_full_prune(tmp_path: pathlib.Path) -> None:
    assert _default_for(["docker_hosts"]) == 0
    assert _run_gate(tmp_path, 0, "10") == ["image prune -f -a", "builder prune -f -a"]


def test_below_the_threshold_only_dangling_images_and_cache_go(tmp_path: pathlib.Path) -> None:
    assert _run_gate(tmp_path, 70, "42") == ["image prune -f", "builder prune -f"]


def test_at_the_threshold_everything_unused_goes(tmp_path: pathlib.Path) -> None:
    assert _run_gate(tmp_path, 70, "70") == ["image prune -f -a", "builder prune -f -a"]


def test_an_unreadable_disk_prunes_everything(tmp_path: pathlib.Path) -> None:
    # Failing toward a full disk would page later and stop CI; failing toward a cold
    # cache costs minutes. The gate takes the cheap side.
    assert _run_gate(tmp_path, 70, "") == ["image prune -f -a", "builder prune -f -a"]


def test_the_ansible_twin_reads_the_same_gate() -> None:
    tasks = yaml.safe_load(_tasks())
    by_name = {t.get("name"): t for t in tasks if isinstance(t, dict)}
    for name in ("Prune unused Docker images", "Prune Docker build cache"):
        assert "_docker_prune_all" in str(by_name[name]["command"]), f"{name} ignores the gate"
    probe = by_name["Measure the filesystem that holds Docker"]
    assert GATE in str(probe["when"])


def test_the_platform_node_prunes_by_pressure_below_its_disk_alert() -> None:
    common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
    groups = common["networking"]["nodes"]["beelink"]["ansible_groups"]
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    alert_expression = str(defaults["maintenance_disk_alert_percent"])
    alert = int(jinja2.Environment().from_string(alert_expression).render(group_names=groups))
    assert 0 < _default_for(groups) < alert, "prune must start before the disk alert fires"


def test_a_df_that_fails_prunes_everything_and_does_not_stop_the_run(tmp_path: pathlib.Path) -> None:
    # Under pipefail a failing `df` would otherwise end the whole maintenance run.
    assert _run_gate(tmp_path, 70, "", df_rc=1) == ["image prune -f -a", "builder prune -f -a"]


@pytest.mark.parametrize(
    ("threshold", "probe", "expected"),
    [
        (0, {"skipped": True}, True),
        (70, {"stdout": ""}, True),
        (70, {"stdout": "69"}, False),
        (70, {"stdout": "70"}, True),
        (70, {"stdout": "85"}, True),
    ],
)
def test_the_ansible_twin_decides_like_the_script(threshold: int, probe: dict, expected: bool) -> None:
    tasks = yaml.safe_load(_tasks())
    decide = next(
        t for t in tasks if isinstance(t, dict) and t.get("name") == "Decide whether the prune takes everything unused"
    )
    rendered = (
        jinja2.Environment()
        .from_string(decide["set_fact"]["_docker_prune_all"])
        .render(maintenance_docker_prune_above_percent=threshold, _docker_fs_percent=probe)
    )
    assert rendered.strip() == str(expected)


# The decision reaches the commands as the text the set_fact rendered.
@pytest.mark.parametrize(("prune_all", "flag"), [("True", " -a"), ("False", "")])
def test_the_ansible_twin_passes_the_decision_to_both_prunes(prune_all: str, flag: str) -> None:
    by_name = {t.get("name"): t for t in yaml.safe_load(_tasks()) if isinstance(t, dict)}
    env = jinja2.Environment()
    # Ansible's `bool` filter, reduced to the spellings a rendered boolean takes.
    env.filters["bool"] = lambda v: v if isinstance(v, bool) else str(v).strip().lower() in ("true", "yes", "on", "1")
    for name, verb in (("Prune unused Docker images", "image"), ("Prune Docker build cache", "builder")):
        argv = env.from_string(by_name[name]["command"]).render(_docker_prune_all=prune_all)
        assert argv == f"docker {verb} prune -f{flag}", name
