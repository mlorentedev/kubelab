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
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parents[1]
PLAYBOOKS = REPO / "infra/ansible/playbooks"
INCLUDE = PLAYBOOKS / "_includes/image-pull.yml"
ESTIMATOR = PLAYBOOKS / "files/image-pull-estimate.py"
AGENT_STACK = REPO / "infra/ansible/roles/agent_stack/tasks/main.yml"
COMMON = REPO / "infra/config/values/common.yaml"
SSOT = "{{ config.networking.edge.uplink.bandwidth.down_kbit }}"

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


def test_a_pull_past_the_budget_is_refused_unless_the_run_allows_it():
    # 1.62 GB at 2970 kbit/s is 4359 s, past the 1800 s default.
    assert _decide(2970, OPEN_WEBUI_BYTES) == (False, 4359 * 2 + 300)
    assert _decide(2970, OPEN_WEBUI_BYTES, image_pull_allow_slow="true")[0]
    assert _decide(2970, OPEN_WEBUI_BYTES, image_pull_budget_seconds=5000)[0]
    assert _decide(2970, 100_000_000) == (True, 270 * 2 + 300)
    assert _decide(2970, 0) == (True, 300), "a held image still gets a bound"


def test_a_node_outside_the_edge_is_not_estimated_and_keeps_a_fixed_bound():
    assert _decide(0, OPEN_WEBUI_BYTES) == (True, 3600)
    assert "image_pull_down_kbit | default(0) | int > 0" in _tasks()["Estimate the download of"]["when"]


def test_the_pull_is_polled_and_retried_rather_than_held():
    pull = _tasks()["Pull"]
    assert pull["poll"] > 0 and pull["until"] == "_image_pull is succeeded"
    assert "image_pull_retries" in str(pull["retries"])
    assert _tasks()["Estimate the download of"]["check_mode"] is False, "a dry run reports the estimate"


def _plays_setting_the_downlink() -> dict[str, str]:
    found = {}
    for path in PLAYBOOKS.glob("*.yml"):
        for play in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            if isinstance(play, dict) and "image_pull_down_kbit" in (play.get("vars") or {}):
                assert play["vars"]["image_pull_down_kbit"] == SSOT, f"{path.name}: read the SSOT, not a copy"
                found[path.name] = play["hosts"]
    return found


def test_only_plays_of_nodes_behind_the_edge_size_their_pulls():
    networking = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["networking"]
    lan = ipaddress.ip_network(networking["lan_cidr"])
    plays = _plays_setting_the_downlink()
    assert plays.get("provision-ace2.yml") == "ace2"
    for name, host in plays.items():
        assert ipaddress.ip_address(networking["nodes"][host]["lan_ip"]) in lan, (
            f"{name}: {host} is not behind the edge"
        )


def test_open_webui_is_pulled_through_the_include():
    text = AGENT_STACK.read_text(encoding="utf-8")
    assert "compose-webui.yml pull" in text
    block = text[text.index("- name: Pull the Open WebUI image") :].split("\n\n")[0]
    assert "_includes/image-pull.yml" in block
    assert 'image_pull_images: ["{{ agent_stack_webui.image }}"]' in block
    assert text.count("compose-webui.yml pull") == 1, "a second, bare pull of the same stack"
