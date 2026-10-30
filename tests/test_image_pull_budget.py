"""An image pull behind the lab edge is sized against its downlink first (#2742).

On 2026-10-27 `make provision NODE=ace2 ENV=prod` failed at "Pull the Open WebUI
image" with an EOF after 52 minutes. The edge shapes the uplink to
`networking.edge.uplink.bandwidth.down_kbit` on purpose (ADR-075), and nothing
said beforehand how long the pull would take.

`_includes/image-pull.yml` estimates the bytes to fetch from the registry, refuses
past a budget unless the run allows it, and bounds each attempt by the estimate.
A play whose node is behind the edge turns it on with `image_pull_down_kbit`.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parents[1]
PLAYBOOKS = REPO / "infra/ansible/playbooks"
INCLUDE = PLAYBOOKS / "_includes/image-pull.yml"
ESTIMATOR = PLAYBOOKS / "files/image-pull-estimate.py"
ROLES = REPO / "infra/ansible/roles"
AGENT_STACK = ROLES / "agent_stack/tasks/main.yml"
COMMON = REPO / "infra/config/values/common.yaml"
SSOT = "{{ config.networking.edge.uplink.bandwidth.down_kbit }}"

# Roles that still pull bare on a node behind the edge, each with what holds it (#2742).
# Converting one removes it here, and a new bare pull fails until it is sized or listed.
UNSIZED_ROLES = {
    "beelink_services": "several images in one stack: which ones the include reads is a ruling",
    "coredns": "the LAN's bootstrap DNS: converted once the include has run on a node",
    "docker": "the smoke pull, a small image under `timeout`: to be declared an exception",
}
# Plays of a node behind the edge that run a sized role without sizing it.
UNSIZED_PLAYS = {"provision-rpi4.yml": "the edge itself: it comes with coredns"}

# Measured on 2026-10-29 for ghcr.io/open-webui/open-webui:v0.12.0 (amd64, 19 layers).
OPEN_WEBUI_BYTES = 1_618_157_731


def _estimator():
    spec = importlib.util.spec_from_file_location("image_pull_estimate", ESTIMATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _entry(arch: str, sizes: list[int]) -> dict:
    return {
        "Descriptor": {"platform": {"architecture": arch, "os": "linux"}},
        "SchemaV2Manifest": {"layers": [{"size": size} for size in sizes]},
    }


def _manifest_list() -> list[dict]:
    attestation = {
        "Descriptor": {"platform": {"architecture": "unknown", "os": "unknown"}},
        "OCIManifest": {"layers": [{"size": 10_462_978}]},
    }
    return [_entry("amd64", [OPEN_WEBUI_BYTES - 100, 100]), attestation, _entry("arm64", [1_461_623_689])]


def test_the_estimate_reads_the_nodes_platform_and_skips_attestations():
    layer_bytes = _estimator().layer_bytes
    assert layer_bytes(_manifest_list(), "amd64") == OPEN_WEBUI_BYTES
    assert layer_bytes(_manifest_list(), "arm64") == 1_461_623_689
    assert layer_bytes(_entry("amd64", [5, 7]), "arm64") == 12, "a single-platform image is taken as it is"
    with pytest.raises(ValueError):
        layer_bytes(_manifest_list(), "riscv64")


def test_an_image_the_node_holds_costs_nothing_and_an_unreadable_one_stops_the_run():
    module = _estimator()
    held = {"present:1"}

    def run(cmd):
        if cmd[1] == "image":
            return subprocess.CompletedProcess(cmd, 0 if cmd[-1] in held else 1, "", "")
        if cmd[-1] == "private:1":
            return subprocess.CompletedProcess(cmd, 1, "", "unauthorized")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(_manifest_list()), "")

    assert module.estimate("amd64", ["present:1", "absent:1"], run=run) == {
        "bytes": OPEN_WEBUI_BYTES,
        "images": [{"image": "present:1", "bytes": 0}, {"image": "absent:1", "bytes": OPEN_WEBUI_BYTES}],
    }
    with pytest.raises(SystemExit, match="private:1"):
        module.estimate("amd64", ["private:1"], run=run)
    assert module.ARCH["x86_64"] == "amd64" and module.ARCH["aarch64"] == "arm64"


def _tasks() -> dict[str, dict]:
    return {task["name"].split(" {{")[0]: task for task in yaml.safe_load(INCLUDE.read_text(encoding="utf-8"))}


def _decide(down_kbit: int, nbytes: int, **extra) -> tuple[bool, int]:
    """What the include decides: whether the pull may start, and its bound in seconds."""
    env = ansible_env(".")
    env.filters["from_json"] = json.loads
    tasks = _tasks()
    names = {"image_pull_down_kbit": down_kbit, "_image_pull_estimate": {"stdout": json.dumps({"bytes": nbytes})}}
    names |= extra
    if down_kbit:
        facts = tasks["Size the pull of"]["ansible.builtin.set_fact"]
        names |= {key: int(env.from_string(value).render(**names)) for key, value in facts.items()}
    allowed = env.from_string("{{ (" + tasks["Refuse a pull of"]["ansible.builtin.assert"]["that"] + ") | bool }}")
    bound = env.from_string(tasks["Pull"]["async"]).render(**names)
    return allowed.render(**names) == "True", int(bound)


def test_the_estimate_is_stated_before_the_pull_whatever_it_decides():
    """`make provision` runs without -v, so a registered estimate alone says nothing."""
    names = list(_tasks())
    assert names.index("State the estimate for") < names.index("Refuse a pull of") < names.index("Pull")
    task = _tasks()["State the estimate for"]
    assert task["when"] == "image_pull_down_kbit | default(0) | int > 0"
    env = ansible_env(".")
    env.filters["from_json"] = json.loads
    images = [{"image": "a:1", "bytes": OPEN_WEBUI_BYTES}, {"image": "b:2", "bytes": 0}]
    message = env.from_string(task["ansible.builtin.debug"]["msg"]).render(
        image_pull_name="Open WebUI",
        image_pull_down_kbit=2970,
        _image_pull_bytes=OPEN_WEBUI_BYTES,
        _image_pull_seconds=4359,
        _image_pull_estimate={"stdout": json.dumps({"bytes": OPEN_WEBUI_BYTES, "images": images})},
    )
    assert message == (
        "Open WebUI: 1.6 GB to fetch (a:1 1.6 GB, b:2 0 Bytes), about 72.7 min at the edge's"
        " 2970 kbit/s, against a budget of 30 min."
    )


def test_a_pull_past_the_budget_is_refused_unless_the_run_allows_it():
    # 1.62 GB at 2970 kbit/s is 4359 s, past the 1800 s default.
    assert _decide(2970, OPEN_WEBUI_BYTES) == (False, 4359 * 2 + 300)
    assert _decide(2970, OPEN_WEBUI_BYTES, image_pull_allow_slow="true")[0]
    assert _decide(2970, OPEN_WEBUI_BYTES, image_pull_budget_seconds=5000)[0]
    assert _decide(2970, 100_000_000) == (True, 270 * 2 + 300)
    assert _decide(2970, 0) == (True, 300), "a held image still gets a bound"


def test_an_explicit_timeout_bounds_the_pull_whatever_the_estimate():
    """The lever when the estimate is wrong: a held tag counts 0, and gets 300 s."""
    assert _decide(2970, 0, image_pull_timeout_seconds="5400") == (True, 5400)
    assert _decide(0, OPEN_WEBUI_BYTES, image_pull_timeout_seconds=900) == (True, 900)


def test_a_node_outside_the_edge_is_not_estimated_and_keeps_a_fixed_bound():
    assert _decide(0, OPEN_WEBUI_BYTES) == (True, 3600)
    assert "image_pull_down_kbit | default(0) | int > 0" in _tasks()["Estimate the download of"]["when"]


def test_the_pull_is_polled_and_retried_rather_than_held():
    pull = _tasks()["Pull"]
    assert pull["poll"] > 0 and pull["until"] == "_image_pull is succeeded"
    assert "image_pull_retries" in str(pull["retries"])
    assert _tasks()["Estimate the download of"]["check_mode"] is False, "a dry run reports the estimate"


def _networking() -> dict:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))["networking"]


def _nodes(hosts: str | list[str], networking: dict) -> set[str]:
    """The nodes a play's `hosts:` names: a node, a group a node declares, or all."""
    nodes = networking["nodes"]
    found: set[str] = set()
    for pattern in hosts if isinstance(hosts, list) else hosts.split(","):
        pattern = pattern.strip()
        if pattern == "all":
            found |= set(nodes)
        elif pattern in nodes:
            found.add(pattern)
        else:
            found |= {name for name, node in nodes.items() if pattern in (node.get("ansible_groups") or [])}
    return found


def _behind_the_edge(node: str, networking: dict) -> bool:
    """On the switch, or on the lab Wi-Fi the edge serves: both leave by its uplink."""
    lan_ip = networking["nodes"][node].get("lan_ip")
    sides = (networking["lan_cidr"], networking["edge"]["lab_wifi"]["cidr"])
    return bool(lan_ip) and any(ipaddress.ip_address(lan_ip) in ipaddress.ip_network(side) for side in sides)


def _plays() -> list[tuple[str, dict]]:
    found = []
    for path in sorted(PLAYBOOKS.glob("*.yml")):
        for play in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            if isinstance(play, dict) and "hosts" in play:
                found.append((path.name, play))
    return found


ROLE_MODULES = ("include_role", "import_role", "ansible.builtin.include_role", "ansible.builtin.import_role")


def _roles(play: dict) -> set[str]:
    """The roles a play runs: its `roles:` list, and any `include_role`/`import_role` in its tasks."""
    found = {Path(entry["role"] if isinstance(entry, dict) else entry).name for entry in play.get("roles") or []}
    for key in ("pre_tasks", "tasks", "post_tasks", "handlers"):
        for task in _task_list(play.get(key)):
            for module in ROLE_MODULES:
                if isinstance(task.get(module), dict):
                    found.add(Path(task[module]["name"]).name)
    return found


def _plays_setting_the_downlink() -> dict[str, str]:
    found = {}
    for name, play in _plays():
        if "image_pull_down_kbit" in (play.get("vars") or {}):
            assert play["vars"]["image_pull_down_kbit"] == SSOT, f"{name}: read the SSOT, not a copy"
            found[name] = play["hosts"]
    return found


def test_only_plays_of_nodes_behind_the_edge_size_their_pulls():
    networking = _networking()
    plays = _plays_setting_the_downlink()
    names = ("provision-ace1.yml", "provision-ace2.yml", "provision-bee.yml", "provision-rpi3.yml")
    assert {plays.get(name) for name in names} == {"ace1", "ace2", "beelink", "rpi3"}
    for name, hosts in plays.items():
        nodes = _nodes(hosts, networking)
        assert nodes and all(_behind_the_edge(node, networking) for node in nodes), (
            f"{name}: {hosts} is not behind the edge"
        )


def test_a_node_on_the_lab_wifi_is_behind_the_edge():
    """The edge serves the lab Wi-Fi from its AP and routes it out the same uplink."""
    networking = _networking()
    wifi = ipaddress.ip_network(networking["edge"]["lab_wifi"]["cidr"])
    on_wifi = {n for n, node in networking["nodes"].items() if node.get("lan_ip") and ipaddress.ip_address(node["lan_ip"]) in wifi}
    assert "rpi3" in on_wifi
    assert all(_behind_the_edge(node, networking) for node in on_wifi)


def _task_list(tasks: list | None):
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        yield task
        for key in ("block", "rescue", "always"):
            yield from _task_list(task.get(key))


def _pulls_bare(task: dict) -> bool:
    """A task that pulls an image without the include: a command, or a module told to."""
    if "_includes/image-pull.yml" in str(task.get("ansible.builtin.import_tasks", task.get("import_tasks", ""))):
        return False
    text = " ".join(
        str(task.get(key, "")) for key in ("command", "shell", "ansible.builtin.command", "ansible.builtin.shell")
    )
    text += " " + " ".join(str(item) for item in task.get("loop") or [])
    image_pull = re.search(r"\bpull\b", text) and re.search(r"\b(docker|compose)\b", text)
    return bool(image_pull) or _module_pulls(task)


def _module_pulls(task: dict) -> bool:
    """community.docker fetches an image the daemon lacks unless told never to."""

    def args(name: str) -> dict | None:
        found = task.get(f"community.docker.{name}", task.get(name))
        return found if isinstance(found, dict) else None

    fetching = [m for m in (args("docker_container"), args("docker_compose_v2")) if m is not None]
    image = args("docker_image") or {}
    return any(m.get("pull") != "never" for m in fetching) or image.get("source") == "pull"


def _roles_pulling_bare() -> set[str]:
    found = set()
    for path in ROLES.glob("*/tasks/*.yml"):
        if any(_pulls_bare(task) for task in _task_list(yaml.safe_load(path.read_text(encoding="utf-8")))):
            found.add(path.parts[-3])
    return found


def test_no_role_on_a_node_behind_the_edge_pulls_outside_the_include():
    networking = _networking()
    behind = set()
    for _, play in _plays():
        if any(_behind_the_edge(node, networking) for node in _nodes(play["hosts"], networking)):
            behind |= _roles(play)
    assert {"glances", "agent_stack"} <= behind, "the resolution lost the roles it was written for"
    assert _roles_pulling_bare() & behind == set(UNSIZED_ROLES)


def test_a_play_behind_the_edge_that_runs_a_sized_pull_sizes_it():
    networking = _networking()
    sized = {path.parts[-3] for path in ROLES.glob("*/tasks/*.yml") if "_includes/image-pull.yml" in path.read_text()}
    assert sized >= {"agent_stack", "glances"}
    unsized = set()
    for name, play in _plays():
        behind = any(_behind_the_edge(node, networking) for node in _nodes(play["hosts"], networking))
        if behind and _roles(play) & sized and "image_pull_down_kbit" not in (play.get("vars") or {}):
            unsized.add(name)
    assert unsized == set(UNSIZED_PLAYS)


def test_open_webui_is_pulled_through_the_include():
    text = AGENT_STACK.read_text(encoding="utf-8")
    assert "compose-webui.yml pull" in text
    block = text[text.index("- name: Pull the Open WebUI image") :].split("\n\n")[0]
    assert "_includes/image-pull.yml" in block
    assert 'image_pull_images: ["{{ agent_stack_webui.image }}"]' in block
    assert text.count("compose-webui.yml pull") == 1, "a second, bare pull of the same stack"


def _imports(path: Path) -> list[dict]:
    return [
        task
        for task in _task_list(yaml.safe_load(path.read_text(encoding="utf-8")))
        if "_includes/image-pull.yml" in str(task.get("ansible.builtin.import_tasks", ""))
    ]


def test_glances_is_pulled_through_the_include():
    (pull,) = _imports(ROLES / "glances/tasks/main.yml")
    assert pull["vars"]["image_pull_images"] == ["{{ glances_image }}"]
    assert pull["vars"]["image_pull_command"].endswith("/compose.yml pull")


def test_uptime_kuma_is_pulled_through_the_include():
    (pull,) = _imports(ROLES / "rpi3_services/tasks/main.yml")
    assert pull["vars"]["image_pull_images"] == ["{{ uptime_kuma_image }}"]
    assert pull["vars"]["image_pull_command"].endswith("/compose.yml pull")


def test_the_hermes_images_are_sized_on_the_agents_own_daemon():
    """Rootless: the daemon that holds them, and that a held image is read from, is the agent's."""
    stack, sandbox = _imports(ROLES / "agent_stack/tasks/hermes.yml")
    compose = (ROLES / "agent_stack/templates/compose-hermes.yml.j2").read_text(encoding="utf-8")
    declared = re.findall(r"^\s+image: (\{\{ [\w.]+ \}\})$", compose, re.MULTILINE)
    assert sorted(stack["vars"]["image_pull_images"]) == sorted(declared), "an image the compose pull fetches unsized"
    assert stack["vars"]["image_pull_command"].endswith("pull")
    assert sandbox["vars"]["image_pull_images"] == ["{{ agent_stack_hermes.sandbox.image }}"]
    assert sandbox["vars"]["image_pull_command"] == "docker pull {{ agent_stack_hermes.sandbox.image }}"
    for task in (stack, sandbox):
        assert task["become_user"] == "{{ agent_stack_agent_user }}"
        assert task["environment"] == "{{ agent_stack_agent_daemon_env }}"


def test_the_guard_reads_image_pulls_and_roles_however_they_are_written():
    assert _pulls_bare({"ansible.builtin.command": "docker compose -f x.yml pull"})
    assert _pulls_bare({"command": "docker {{ item }}", "loop": ["pull a:1"]})
    assert _pulls_bare({"community.docker.docker_container": {"name": "x", "pull": True}})
    assert _pulls_bare({"ansible.builtin.command": {"argv": ["docker", "pull", "a:1"]}})
    # The docker modules fetch an image the daemon lacks unless told never to.
    assert _pulls_bare({"community.docker.docker_container": {"name": "x", "image": "a:1"}})
    assert _pulls_bare({"docker_container": {"name": "x", "image": "a:1", "pull": False}})
    assert not _pulls_bare({"community.docker.docker_container": {"name": "x", "image": "a:1", "pull": "never"}})
    assert _pulls_bare({"community.docker.docker_compose_v2": {"project_src": "/opt/x"}})
    assert not _pulls_bare({"community.docker.docker_compose_v2": {"project_src": "/opt/x", "pull": "never"}})
    assert _pulls_bare({"community.docker.docker_image": {"name": "a:1", "source": "pull"}})
    assert not _pulls_bare({"community.docker.docker_image": {"name": "a:1", "source": "local"}})
    assert not _pulls_bare({"ansible.builtin.command": "git -C /opt/x pull --ff-only"})
    play = {"roles": ["../roles/a"], "tasks": [{"block": [{"include_role": {"name": "../roles/b"}}]}]}
    play["pre_tasks"] = [{"ansible.builtin.import_role": {"name": "c"}}]
    assert _roles(play) == {"a", "b", "c"}
