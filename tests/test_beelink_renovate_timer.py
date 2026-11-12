"""Something runs the Gitea Renovate run, hourly, and a stopped forge fails nothing (IDP-036 AC2).

Until this change the global config and the engine pin were installed on the Beelink
and nothing read them. The unit that does is a `Type=oneshot` service driven by an
hourly timer. Three properties are worth a test, and none of them is "the file parses":

- **A stopped forge on a running node fails nothing.** The run's wrapper probes Gitea
  first and, when it does not answer, logs one line and exits 0. That is behaviour, so
  it is executed here against stub `curl`, `docker` and `sleep` binaries.
- **The token reaches the container and nothing declares it twice.** The environment
  file carries the platform, endpoint, token and config path; the global config
  declares none of them, because Renovate merges the two and a second source of the
  same option is the one that silently wins.
- **The image the unit runs is the image the provision pulled.** The unit runs with
  `--pull never` (a pull inside a unit is cut at its timeout on the lab's uplink, and
  retried from nothing), so an engine missing from the bounded pull is a unit that
  fails on every tick.

The role gates the whole run on the account and its token being declared and recorded,
so a forge without them gets no timer, and one that has one stops it.
"""

from __future__ import annotations

import ast
import re
import stat
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml
from jinja2 import StrictUndefined

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/beelink_services"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
SCRIPT = ROLE / "files/renovate-run.sh"

SERVICE = "kubelab-renovate.service"
TIMER = "kubelab-renovate.timer"
DEPLOY_DIR = "/opt/kubelab"
TOKEN = "tok-not-a-real-secret"  # noqa: S105 - a fixture, rendered into a temp file only
GITEA_HEALTH = f"http://{COMMON['networking']['nodes']['beelink']['tailscale_ip']}:{COMMON['apps']['services']['core']['gitea']['default_port']}{COMMON['apps']['services']['core']['gitea']['health_path']}"


# --------------------------------------------------------------------------- helpers


def _defaults() -> dict[str, Any]:
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


def _tasks() -> list[dict[str, Any]]:
    return [t for t in yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8")) if isinstance(t, dict)]


def _task(name: str) -> dict[str, Any]:
    for task in _tasks():
        if task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r} in beelink_services/tasks/main.yml")


def _context(**overrides: Any) -> dict[str, Any]:
    gitea = COMMON["apps"]["services"]["core"]["gitea"]
    context: dict[str, Any] = {
        "ansible_managed": "Ansible managed",
        "beelink_deploy_dir": DEPLOY_DIR,
        "tailscale_ip": COMMON["networking"]["nodes"]["beelink"]["tailscale_ip"],
        "gitea_http_port": gitea["default_port"],
        "gitea_health_path": gitea["health_path"],
        "gitea_renovate_token": TOKEN,
        "gitea_renovate_user": COMMON["apps"]["auth"]["identities"]["renovate"],
        "renovate_engine": {"image": "example/renovate", "version": "1.2.3"},
    }
    context.update({k: v for k, v in _defaults().items() if k.startswith("renovate_") and k not in context})
    context.update(overrides)
    return context


def _render(template: str, **overrides: Any) -> str:
    env = ansible_env(str(ROLE / "templates"), undefined=StrictUndefined)
    context = _context(**overrides)
    # Role defaults are templates themselves (`renovate_enabled`), rendered by Ansible lazily.
    for key, value in list(context.items()):
        if isinstance(value, str) and "{{" in value:
            context[key] = env.from_string(value).render(**context)
    return env.get_template(template).render(**context)


def _settings(rendered: str) -> list[str]:
    return [line for line in rendered.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _env_file(**overrides: Any) -> dict[str, str]:
    pairs = [line.partition("=") for line in _settings(_render("renovate.env.j2", **overrides))]
    return {key: value for key, _, value in pairs}


def _unit(template: str, **overrides: Any) -> dict[str, dict[str, list[str]]]:
    """A rendered unit as {section: {directive: [values]}}, from executable lines only.

    The templates explain every choice in comments that name the directives involved,
    so scanning the whole text would match the prose whether or not the line exists.
    """
    sections: dict[str, dict[str, list[str]]] = {}
    section = ""
    for line in _settings(_render(template, **overrides)):
        if line.startswith("["):
            section = line.strip("[]")
            sections.setdefault(section, {})
        else:
            key, _, value = line.partition("=")
            sections[section].setdefault(key, []).append(value)
    return sections


def _enabled(user: str, token: str) -> bool:
    expression = _defaults()["renovate_enabled"]
    env = ansible_env(".")
    rendered = env.from_string(expression).render(gitea_renovate_user=user, gitea_renovate_token=token)
    return rendered.strip() == "True"


# --------------------------------------------------------------------------- AC6: the identity


def test_the_renovate_login_is_declared_and_distinct() -> None:
    identities = COMMON["apps"]["auth"]["identities"]
    assert identities["renovate"] == "proteo"
    logins = list(identities.values())
    assert len(logins) == len(set(logins)), "two identities share a login"


# --------------------------------------------------------------------------- the environment file


def test_the_env_file_delivers_the_token_the_platform_the_endpoint_and_the_config() -> None:
    env = _env_file()
    assert env["RENOVATE_TOKEN"] == TOKEN
    assert env["RENOVATE_PLATFORM"] == "gitea"
    assert env["RENOVATE_IMAGE"] == "example/renovate:1.2.3"
    assert env["RENOVATE_CONFIG_FILE"].endswith("config.yaml")


def test_the_endpoint_is_the_forge_on_the_compose_network_like_act_runner() -> None:
    """The container joins the stack's network and reaches Gitea by its container name,
    which does not depend on DNS, TLS or the tailnet being up (compose.yml.j2)."""
    compose = (ROLE / "templates/compose.yml.j2").read_text(encoding="utf-8")
    (instance,) = re.findall(r'GITEA_INSTANCE_URL:\s*"([^"]+)"', compose)
    assert _env_file()["RENOVATE_ENDPOINT"] == f"{instance}/api/v1"
    assert re.search(r"container_name:\s*gitea\s*$", compose, re.M), "the endpoint names the container"


def test_no_env_variable_is_set_twice() -> None:
    keys = [line.partition("=")[0] for line in _settings(_render("renovate.env.j2"))]
    assert len(keys) == len(set(keys)), keys


def test_the_global_config_declares_nothing_the_env_file_sets() -> None:
    """Renovate merges the env and the file; a second declaration is the one that wins."""
    config = yaml.safe_load(
        ansible_env(str(ROLE / "templates"), undefined=StrictUndefined)
        .get_template("renovate-config.yaml.j2")
        .render(
            ansible_managed="Ansible managed",
            renovate_gitea_organizations={},
            renovate_preset_tag=COMMON["ci"]["renovate"]["preset_tag"],
        )
    )
    assert not {"platform", "endpoint", "token"} & set(config)


def test_the_env_file_stays_0600_and_its_task_keeps_the_token_out_of_the_log() -> None:
    task = _task("Install the Renovate run environment")
    assert task["template"]["mode"] == "0600"
    assert task["no_log"] is True, "the task now carries the token in its diff"


def test_the_configured_path_is_the_one_the_container_mounts_the_config_at(tmp_path: Path) -> None:
    stub = _run_script(tmp_path, gitea_up=True)
    mount = _env_file()["RENOVATE_CONFIG_FILE"]
    volumes = [arg for arg in stub.docker_run_args if arg.endswith(f":{mount}:ro")]
    assert volumes == [f"{DEPLOY_DIR}/renovate/config.yaml:{mount}:ro"]


# --------------------------------------------------------------------------- the timer


def test_the_timer_is_hourly_and_catches_up_a_run_a_powered_off_node_missed() -> None:
    timer = _unit("kubelab-renovate.timer.j2")
    assert timer["Timer"]["OnCalendar"] == ["hourly"]
    assert timer["Timer"]["Persistent"] == ["true"]
    assert timer["Install"]["WantedBy"] == ["timers.target"]


def test_the_service_is_a_bounded_oneshot_after_the_forge_stack() -> None:
    unit = _unit("kubelab-renovate.service.j2")
    assert unit["Service"]["Type"] == ["oneshot"]
    assert unit["Service"]["EnvironmentFile"] == [f"{DEPLOY_DIR}/renovate/renovate.env"]
    (timeout,) = unit["Service"]["TimeoutStartSec"]
    assert re.fullmatch(r"\d+(s|min|m|h)", timeout), "a oneshot's start is unbounded without this"
    assert "kubelab-compose.service" in unit["Unit"]["After"][0].split()
    assert "docker.service" in unit["Unit"]["Requires"][0].split()
    # Wants= would start the whole stack from a timer tick; ordering is all the run needs.
    assert not any("kubelab-compose" in v for v in unit["Unit"].get("Requires", []) + unit["Unit"].get("Wants", []))


def test_the_service_hands_the_wrapper_every_value_it_needs_and_the_wrapper_defaults_none() -> None:
    unit = _unit("kubelab-renovate.service.j2")
    exec_start = unit["Service"]["ExecStart"]
    assert exec_start == [f"{DEPLOY_DIR}/renovate-run.sh"]
    given = {pair.split("=", 1)[0] for value in unit["Service"]["Environment"] for pair in _split_env(value)}
    script = SCRIPT.read_text(encoding="utf-8")
    needed = set(re.findall(r"\$\{(KUBELAB_RENOVATE_\w+):\?", script))
    assert needed and needed <= given, f"the unit does not set {needed - given}"
    assert not re.search(r"\$\{KUBELAB_RENOVATE_\w+:-", script), "a default is a second declaration"


def _split_env(value: str) -> list[str]:
    return [p.strip('"') for p in re.findall(r'(?:[^\s"]|"[^"]*")+', value)]


def test_the_service_probes_the_forge_where_the_provision_does() -> None:
    unit = _unit("kubelab-renovate.service.j2")
    env = dict(pair.split("=", 1) for value in unit["Service"]["Environment"] for pair in _split_env(value))
    assert env["KUBELAB_RENOVATE_HEALTH_URL"] == GITEA_HEALTH
    assert env["KUBELAB_RENOVATE_NETWORK"] == "kubelab"
    assert env["KUBELAB_RENOVATE_MEMORY"] == _defaults()["renovate_memory_limit"] == "1g"


def test_the_network_is_the_one_compose_declares() -> None:
    """`docker run --network` takes the network's real name, not compose's project-prefixed one."""
    compose = (ROLE / "templates/compose.yml.j2").read_text(encoding="utf-8")
    assert re.search(r"^networks:\n  kubelab:\n    name: kubelab\n    external: true", compose, re.M)


# --------------------------------------------------------------------------- the wrapper, executed


class Stub:
    def __init__(self, calls: list[list[str]], output: str, status: int) -> None:
        self.calls = calls
        self.output = output
        self.status = status

    @property
    def docker_run_args(self) -> list[str]:
        for call in self.calls:
            if call[:1] == ["run"]:
                return call
        return []

    def docker_verbs(self) -> list[str]:
        return [call[0] for call in self.calls if call]


def _run_script(
    root: Path, *, gitea_up: bool, docker_status: int = 0, probes_before_up: int = 0, with_curl: bool = True
) -> Stub:
    bin_dir = root / "bin"
    bin_dir.mkdir()
    log = root / "docker.log"
    counter = root / "curl.count"
    counter.write_text("0", encoding="utf-8")
    stubs = {
        "curl": f"""
            n=$(cat {counter}); n=$((n + 1)); echo "$n" > {counter}
            printf '%s\\n' "$*" >> {root}/curl.log
            {"[ \"$n\" -gt " + str(probes_before_up) + " ]" if gitea_up else "false"}
        """,
        "docker": f"""
            printf '%s\\n' "$*" >> {log}
            [ "$1" = run ] && exit {docker_status}
            exit 0
        """,
        "sleep": "exit 0",
    }
    for name, body in stubs.items():
        if name == "curl" and not with_curl:
            continue
        path = bin_dir / name
        path.write_text("#!/bin/sh\n" + textwrap.dedent(body), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    unit = _unit("kubelab-renovate.service.j2")
    # Without curl the PATH is the stub directory alone: the script uses nothing else.
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin" if with_curl else str(bin_dir), "RENOVATE_IMAGE": "example/renovate:1.2.3"}
    for value in unit["Service"]["Environment"]:
        env.update(pair.split("=", 1) for pair in _split_env(value))
    proc = subprocess.run(  # noqa: S603 - a repo script under test
        ["/bin/sh", str(SCRIPT)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False
    )
    calls = [line.split() for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return Stub(calls, proc.stdout + proc.stderr, proc.returncode)


def test_a_stopped_forge_is_a_logged_skip_and_exit_zero_not_a_failure(tmp_path: Path) -> None:
    result = _run_script(tmp_path, gitea_up=False)
    assert result.status == 0
    assert result.calls == [], f"docker was called against a forge that did not answer: {result.calls}"
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 1 and "skip" in lines[0].lower() and GITEA_HEALTH in lines[0]


def test_a_missing_curl_fails_the_unit_instead_of_skipping_every_run_forever(tmp_path: Path) -> None:
    """Without it the probe reads `command not found` as "Gitea did not answer": exit 0, hourly, no run."""
    result = _run_script(tmp_path, gitea_up=True, with_curl=False)
    assert result.status != 0
    assert "curl" in result.output and result.calls == []


def test_the_wait_for_the_forge_is_bounded_at_about_thirty_seconds() -> None:
    """The probes are what bound it: count them against the script's own budget."""
    script = SCRIPT.read_text(encoding="utf-8")
    tries = int(re.search(r"^tries=(\d+)$", script, re.M).group(1))
    per_probe = int(re.search(r"--max-time\s+(\d+)", script).group(1)) + int(
        re.search(r"^\s*sleep\s+(\d+)$", script, re.M).group(1)
    )
    assert 25 <= tries * per_probe <= 35


def test_a_forge_that_answers_late_still_gets_its_run(tmp_path: Path) -> None:
    result = _run_script(tmp_path, gitea_up=True, probes_before_up=3)
    assert result.status == 0
    assert result.docker_run_args, "the forge answered within the wait and nothing ran"


def test_a_failed_run_fails_the_unit(tmp_path: Path) -> None:
    assert _run_script(tmp_path, gitea_up=True, docker_status=1).status == 1


def test_the_run_is_a_capped_throwaway_that_never_pulls(tmp_path: Path) -> None:
    args = _run_script(tmp_path, gitea_up=True).docker_run_args
    assert "--rm" in args
    assert args[args.index("--network") + 1] == "kubelab"
    assert args[args.index("--memory") + 1] == "1g"
    assert args[args.index("--name") + 1] == "kubelab-renovate"
    assert args[args.index("--pull") + 1] == "never"
    assert args[args.index("--env-file") + 1] == f"{DEPLOY_DIR}/renovate/renovate.env"
    assert args[-1] == "example/renovate:1.2.3", "the engine is the pinned image, last"
    assert "-v" in args and "--volume" not in args
    assert not [a for a in args if a.startswith("-e") or a == "--env"], "the token must not ride the command line"


def test_a_leftover_container_of_a_killed_run_does_not_block_the_next_one(tmp_path: Path) -> None:
    verbs = _run_script(tmp_path, gitea_up=True).docker_verbs()
    assert verbs.index("rm") < verbs.index("run")


def test_no_cache_volume_is_mounted(tmp_path: Path) -> None:
    args = _run_script(tmp_path, gitea_up=True).docker_run_args
    assert args.count("-v") == 1, "one mount, the config: no cache volume"


def test_the_wrapper_is_executable_posix_sh() -> None:
    assert SCRIPT.read_text(encoding="utf-8").startswith("#!/bin/sh\n")
    task = _task("Install the Renovate run wrapper")
    assert task["copy"]["mode"] == "0755"
    assert task["copy"]["dest"] == "{{ beelink_deploy_dir }}/renovate-run.sh"


# --------------------------------------------------------------------------- the gate


@pytest.mark.parametrize(
    ("user", "token", "enabled"),
    [("proteo", "tok", True), ("", "tok", False), ("proteo", "", False), ("", "", False)],
)
def test_the_run_is_enabled_only_when_the_account_and_its_token_both_exist(user: str, token: str, enabled: bool) -> None:
    assert _enabled(user, token) is enabled


RENOVATE_UNIT_TASKS = [
    "Install the Renovate run wrapper",
    "Install the Renovate service unit",
    "Install the Renovate timer unit",
    "Enable and start the Renovate timer",
]


@pytest.mark.parametrize("name", RENOVATE_UNIT_TASKS)
def test_every_unit_task_runs_only_when_the_run_is_enabled(name: str) -> None:
    assert "renovate_enabled | bool" in str(_task(name)["when"])


def test_a_timed_out_run_does_not_leave_its_engine_running() -> None:
    unit = _unit("kubelab-renovate.service.j2")
    assert unit["Service"]["ExecStopPost"] == ["-/usr/bin/docker rm -f ${KUBELAB_RENOVATE_NAME}"]


def test_no_task_rewrites_the_values_the_run_gate_reads() -> None:
    # The pull and the unit tasks agree within one play only because the gate's
    # inputs are the play's own vars, read once from SOPS. A set_fact on either
    # would let the timer start in the same run that skipped the engine's pull.
    for task in _tasks():
        facts = task.get("set_fact") or task.get("ansible.builtin.set_fact") or {}
        assert not {"gitea_renovate_user", "gitea_renovate_token", "renovate_enabled"} & set(facts), task.get("name")


def test_a_disabled_run_stops_a_timer_it_left_behind_and_fails_nothing() -> None:
    probe = _task("Look for a Renovate timer left by an earlier provision")
    assert probe["stat"]["path"] == f"/etc/systemd/system/{TIMER}"
    stop = _task("Stop and disable the Renovate timer when the run is not enabled")
    assert stop["systemd"] == {"name": TIMER, "enabled": False, "state": "stopped"}
    when = " ".join(map(str, stop["when"] if isinstance(stop["when"], list) else [stop["when"]]))
    assert "not (renovate_enabled | bool)" in when
    assert "_renovate_timer_present.stat.exists" in when


def test_the_unit_installs_notify_a_reload_that_exists() -> None:
    handlers = {h["name"] for h in yaml.safe_load((ROLE / "handlers/main.yml").read_text(encoding="utf-8"))}
    for name in ("Install the Renovate service unit", "Install the Renovate timer unit"):
        assert _task(name)["notify"] in handlers


def test_the_timer_is_started_under_the_same_tags_as_the_rest_of_the_run() -> None:
    for name in RENOVATE_UNIT_TASKS:
        assert {"gitea", "renovate"} <= set(_task(name)["tags"])


def test_no_renovate_task_runs_a_command_that_always_reports_a_change() -> None:
    """Idempotence: a command or shell task with no `changed_when` is `changed` on every run."""
    offenders = []
    for task in _tasks():
        if "renovate" not in " ".join(map(str, task.get("tags") or [])) and "Renovate" not in str(task.get("name")):
            continue
        if {"command", "shell", "ansible.builtin.command", "ansible.builtin.shell"} & set(task):
            if "changed_when" not in task and "creates" not in str(task):
                offenders.append(task["name"])
    assert not offenders, offenders


def test_the_memory_cap_is_declared_once_with_its_open_measurement() -> None:
    text = (ROLE / "defaults/main.yml").read_text(encoding="utf-8")
    assert _defaults()["renovate_memory_limit"] == "1g"
    block = text[: text.index("renovate_memory_limit")]
    assert "#1384" in block[-800:], "the peak is measured on the first run and recorded there"


# --------------------------------------------------------------------------- the image pull


def _pull_images(**variables: Any) -> list[str]:
    pull = _tasks()[0]
    assert pull["name"] == "Pull the service images", "the pull is the role's first task (#2812)"
    expression = pull["vars"]["image_pull_images"]
    env = ansible_env(".", undefined=StrictUndefined)
    context = {
        "gitea_image": "gitea/gitea:1",
        "runner_image": "runner:1",
        "act_runner_image": "act:1",
        "runner_enabled": False,
        "act_runner_enabled": True,
        "renovate_engine": {"image": "example/renovate", "version": "1.2.3"},
        "renovate_enabled": True,
        "gitea_renovate_user": "x",
        "gitea_renovate_token": "y",
    }
    context.update(variables)
    return ast.literal_eval(env.from_string(expression).render(**context))


def test_the_engine_is_pulled_when_the_run_is_enabled_and_only_then() -> None:
    engine = f"{_env_file()['RENOVATE_IMAGE']}"
    assert engine in _pull_images(), "the unit runs --pull never: an unpulled engine fails every tick"
    assert engine not in _pull_images(renovate_enabled=False), "a multi-GB pull for a run nothing starts"


def test_the_pulled_image_is_the_image_the_env_file_hands_the_unit() -> None:
    """Both come from the one fetched pin; they cannot name different tags."""
    engine = {"image": "other/renovate", "version": "9.9.9"}
    assert _env_file(renovate_engine=engine)["RENOVATE_IMAGE"] in _pull_images(renovate_engine=engine)


def test_the_pull_also_runs_under_the_renovate_tag() -> None:
    """`--tags renovate` installs the timer; without the pull it would fail on every tick."""
    assert "renovate" in _tasks()[0]["tags"]
