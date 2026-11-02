"""A package upgrade behind the lab edge is sized against its downlink first (#2809).

On 2026-10-29 `make provision NODE=ace1 ENV=prod` sat on "Upgrade all packages" for
about 30 minutes with nothing printed: 29 of them fetching 27 packages through the
uplink the edge shapes (ADR-075), 48 seconds installing them.

`_includes/apt-upgrade.yml` reads the bytes the upgrade would fetch, states them,
fetches them in a bounded, retried download, and skips the upgrade past the budget
instead of failing the play. It reads the image-pull include's vars (#2742).
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import yaml
from jinja2 import StrictUndefined

from tests.ansible_jinja import ansible_env
from tests.test_image_pull_budget import _behind_the_edge, _networking, _nodes, _plays, _roles, _task_list

REPO = Path(__file__).resolve().parents[1]
INCLUDE = REPO / "infra/ansible/playbooks/_includes/apt-upgrade.yml"
ROLES = REPO / "infra/ansible/roles"
BASE_SYSTEM = ROLES / "base_system/tasks/main.yml"

ESTIMATE = "Estimate the package upgrade's download"
NOTICE = "Skip a package upgrade that outlasts its budget"
DOWNLOAD = "Download the package upgrade"
UPGRADE = "Upgrade all packages"

# What `apt-get --print-uris` printed on 2026-10-29 for a package not in the cache.
PRINTED = (
    "'http://us.archive.ubuntu.com/ubuntu/pool/universe/c/cowsay/cowsay_3.03%2bdfsg2-8build1_all.deb'"
    " cowsay_3.03+dfsg2-8build1_all.deb 18100 MD5Sum:ad8b4bd64b736232c8ba6f1efaa5bd58"
)
# Past the 30 min default at 2970 kbit/s: 2694 s.
LARGE = 1_000_000_000


def _tasks() -> dict[str, dict]:
    return {task["name"]: task for task in yaml.safe_load(INCLUDE.read_text(encoding="utf-8"))}


def _runs(task: dict, names: dict) -> bool:
    """Ansible's reading of a `when`: every condition true, evaluated in order."""
    env = ansible_env(".", undefined=StrictUndefined)
    conditions = task.get("when", [])
    conditions = conditions if isinstance(conditions, list) else [conditions]
    return all(env.from_string("{{ (" + c + ") | bool }}").render(**names) == "True" for c in conditions)


def _play(down_kbit: int, nbytes: int, **extra) -> tuple[set[str], int | None]:
    """The include's tasks that run, in order, and the download's bound in seconds.

    Undefined names raise, so a task outside the edge that reads a fact only the
    sized path sets fails here instead of rendering as empty.
    """
    env = ansible_env(".", undefined=StrictUndefined)
    names: dict = {"image_pull_down_kbit": down_kbit} | extra
    ran = set()
    for name, task in _tasks().items():
        if not _runs(task, names):
            continue
        ran.add(name)
        if name == ESTIMATE:
            names["_apt_upgrade_estimate"] = {"stdout": str(nbytes)}
        if "ansible.builtin.set_fact" in task:
            scope = dict(names)
            for key, value in task.get("vars", {}).items():
                scope[key] = env.from_string(value).render(**scope)
            names |= {key: env.from_string(v).render(**scope) for key, v in task["ansible.builtin.set_fact"].items()}
    bound = int(env.from_string(_tasks()[DOWNLOAD]["async"]).render(**names)) if DOWNLOAD in ran else None
    return ran, bound


def test_a_node_outside_the_edge_upgrades_as_it_always_has():
    ran, _ = _play(0, LARGE)
    assert ran == {UPGRADE}
    assert _tasks()[UPGRADE]["ansible.builtin.apt"] == {"upgrade": "dist"}
    assert "async" not in _tasks()[UPGRADE], "nothing bounds dpkg"


def test_an_upgrade_within_its_budget_downloads_first_then_installs():
    ran, bound = _play(2970, 100_000_000)
    assert ran == {
        ESTIMATE,
        "Size the package upgrade against the edge's downlink",
        "State the estimate for the package upgrade",
        DOWNLOAD,
        UPGRADE,
    }
    assert bound == 270 * 2 + 300
    assert list(_tasks()).index(DOWNLOAD) < list(_tasks()).index(UPGRADE)


def test_an_upgrade_past_its_budget_is_skipped_and_said_so_never_failed():
    """Failing here would drop the handlers base_system notified before it (#2812)."""
    ran, _ = _play(2970, LARGE)
    assert NOTICE in ran and DOWNLOAD not in ran and UPGRADE not in ran
    assert not {"ansible.builtin.assert", "ansible.builtin.fail", "assert", "fail"} & {
        key for task in _tasks().values() for key in task
    }
    ran, bound = _play(2970, LARGE, image_pull_allow_slow="true")
    assert {DOWNLOAD, UPGRADE} <= ran and NOTICE not in ran
    assert bound == 2694 * 2 + 300
    assert {DOWNLOAD, UPGRADE} <= _play(2970, LARGE, image_pull_budget_seconds=1800 * 2)[0]


def test_nothing_left_to_fetch_skips_the_download_and_upgrades_from_the_cache():
    """A rerun, or a retry after a broken download, estimates what the cache lacks."""
    ran, _ = _play(2970, 0)
    assert DOWNLOAD not in ran and UPGRADE in ran


def test_an_explicit_timeout_bounds_the_download_whatever_the_estimate():
    assert _play(2970, 100_000_000, image_pull_timeout_seconds="5400")[1] == 5400


def test_the_skip_names_its_size_and_its_way_out():
    env = ansible_env(".", undefined=StrictUndefined)
    names = {"image_pull_down_kbit": 2970, "_apt_upgrade_bytes": str(LARGE), "_apt_upgrade_seconds": "2694"}
    notice = env.from_string(_tasks()[NOTICE]["ansible.builtin.debug"]["msg"]).render(**names)
    assert notice.startswith("SKIPPED: the package upgrade fetches 1.0 GB, about 45 min at the edge's 2970 kbit/s")
    assert "FIX: rerun with EXTRA='image_pull_allow_slow=true'" in notice
    stated = env.from_string(_tasks()["State the estimate for the package upgrade"]["ansible.builtin.debug"]["msg"])
    assert stated.render(**names) == (
        "Package upgrade: 1.0 GB to fetch, about 44.9 min at the edge's 2970 kbit/s, against a budget of 30 min."
    )


def _estimate(apt: str) -> subprocess.CompletedProcess:
    """The estimate's shell, with `apt-get` replaced by a command that prints `apt`'s output."""
    shell = _tasks()[ESTIMATE]["ansible.builtin.shell"]
    real = "apt-get -qq --print-uris dist-upgrade"
    assert real in shell
    return subprocess.run(["bash", "-c", shell.replace(real, apt)], capture_output=True, text=True, check=False)


def test_the_estimate_sums_the_size_apt_prints_for_each_package_it_would_fetch():
    lines = [PRINTED, PRINTED.replace(" 18100 ", " 5000 ")]
    assert _estimate(f"printf '%s\\n' {' '.join(shlex.quote(line) for line in lines)}").stdout == "23100\n"
    assert _estimate("true").stdout == "0\n", "nothing to fetch"
    assert _estimate("false").returncode != 0, "an apt that cannot answer stops the run, not an estimate of 0"
    assert _tasks()[ESTIMATE]["check_mode"] is False, "a dry run reports the estimate"


def test_the_estimate_the_download_and_the_upgrade_resolve_the_same_upgrade():
    tasks = _tasks()
    assert "dist-upgrade" in tasks[ESTIMATE]["ansible.builtin.shell"]
    assert tasks[DOWNLOAD]["ansible.builtin.command"].endswith("--download-only dist-upgrade")
    assert tasks[UPGRADE]["ansible.builtin.apt"]["upgrade"] == "dist"


def test_base_system_upgrades_through_the_include_after_the_cache_and_the_holds():
    tasks = list(_task_list(yaml.safe_load(BASE_SYSTEM.read_text(encoding="utf-8"))))
    names = [task["name"] for task in tasks]
    at = next(
        i for i, t in enumerate(tasks) if "_includes/apt-upgrade.yml" in str(t.get("ansible.builtin.import_tasks"))
    )
    assert names.index("Update apt cache") < at
    assert names.index("Hold the packages this node upgrades only on purpose") < at
    assert at < names.index("Hold them again after a run that released them")
    assert tasks[at]["when"] == "not (legacy_python | default(false))"


# Upgrades on a node behind the edge that stay outside the include, each with why. It
# may only shrink: a new upgrade outside the include fails until it is sized or listed.
UNSIZED_UPGRADES = {
    "node_maintenance: Apply security updates": (
        "`make maintain` only, the security pocket of installed packages: provisions run the role"
        " with maintenance_run_cleanup false, and the include sizes a dist-upgrade, a different set"
    ),
}

UPGRADE_COMMAND = re.compile(r"\bapt(?:-get)?\b[^|;&\n]*\b(?:dist-upgrade|full-upgrade|upgrade)\b")


def _upgrades(task: dict) -> bool:
    """A task that upgrades packages: the apt module told to, or an apt command line."""
    for module in ("apt", "ansible.builtin.apt"):
        args = task.get(module)
        if isinstance(args, dict):
            if str(args.get("upgrade", "no")).lower() not in {"no", "false"}:
                return True
            if args.get("name") in ("*", ["*"]) and args.get("state") == "latest":
                return True
    keys = ("command", "shell", "raw", "ansible.builtin.command", "ansible.builtin.shell", "ansible.builtin.raw")
    text = " ".join(str(task.get(key, "")) for key in keys)
    return bool(UPGRADE_COMMAND.search(text))


def test_the_upgrade_detector_sees_the_includes_own_upgrades():
    tasks = _tasks()
    assert _upgrades(tasks[UPGRADE]) and _upgrades(tasks[DOWNLOAD]) and _upgrades(tasks[ESTIMATE])
    assert _upgrades({"apt": {"name": "*", "state": "latest"}})
    assert _upgrades({"raw": "apt-get -y dist-upgrade"}), "base_system's legacy path runs apt through raw"
    assert not _upgrades({"apt": {"name": "curl", "state": "present"}})
    assert not _upgrades({"apt": {"update_cache": True, "upgrade": False}})


def test_no_role_on_a_node_behind_the_edge_upgrades_outside_the_include():
    """The weekly timer's twin of node_maintenance's patch step is a script, not a task,
    so this does not read it."""
    networking = _networking()
    behind, found = set(), set()
    for name, play in _plays():
        if any(_behind_the_edge(node, networking) for node in _nodes(play["hosts"], networking)):
            behind |= _roles(play)
            for key in ("pre_tasks", "tasks", "post_tasks", "handlers"):
                found |= {f"{name}: {t.get('name')}" for t in _task_list(play.get(key)) if _upgrades(t)}
    assert "base_system" in behind, "the resolution lost the role it was written for"
    read = set()
    for path in [*ROLES.glob("*/tasks/**/*.yml"), *ROLES.glob("*/handlers/**/*.yml")]:
        role = path.relative_to(ROLES).parts[0]
        if role in behind:
            read.add(path.relative_to(ROLES).as_posix())
            tasks = _task_list(yaml.safe_load(path.read_text(encoding="utf-8")))
            found |= {f"{role}: {t.get('name')}" for t in tasks if _upgrades(t)}
    assert {"base_system/tasks/main.yml", "base_system/handlers/main.yml"} <= read, sorted(read)
    assert found == set(UNSIZED_UPGRADES)
