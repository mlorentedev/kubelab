"""Open WebUI searches the web through SearXNG on ace2 (spec AI-025, #2915).

v0.12.5 takes one `WEB_SEARCH_ENGINE` and has no fallback, so the engine that
aggregates others is SearXNG itself. It runs beside Open WebUI on that project's
network, with no port, and nothing but Open WebUI asks it anything.
"""

from __future__ import annotations

import json

import yaml

from tests.test_agent_stack_role import _common, _env, _render, _tasks, _template_task


def _search() -> dict:
    return _common()["apps"]["services"]["ai"]["open_webui"]["web_search"]


def _searxng_service() -> dict:
    return yaml.safe_load(_render("compose-webui.yml.j2"))["services"]["searxng"]


def test_searxng_runs_beside_open_webui_with_no_port() -> None:
    service = _searxng_service()
    assert service["image"] == _search()["searxng"]["image"]
    # A published port would let any tailnet peer use it; ufw cannot restrict one.
    assert "ports" not in service
    assert service["mem_limit"] == _search()["searxng"]["memory_limit"]
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]


def test_the_settings_are_mounted_read_only_and_the_secret_is_not_in_them() -> None:
    service = _searxng_service()
    assert any(v.endswith(":/etc/searxng/settings.yml:ro") for v in service["volumes"]), service["volumes"]
    settings = yaml.safe_load(_render("searxng-settings.yml.j2"))
    # Open WebUI asks for `format=json`; SearXNG answers 403 to a format it does not list.
    assert "json" in settings["search"]["formats"]
    # The limiter needs Valkey and only ever sees Open WebUI's address.
    assert settings["server"]["limiter"] is False
    assert "secret_key" not in settings["server"], "the key comes from SEARXNG_SECRET"


def test_the_searxng_key_is_generated_on_the_node_and_kept_out_of_compose() -> None:
    compose = _render("compose-webui.yml.j2")
    assert "searxng-key-sentinel" not in compose
    task = _template_task("searxng.env.j2")
    assert task["ansible.builtin.template"]["mode"] == "0600"
    assert task.get("no_log") is True
    assert "SEARXNG_SECRET=searxng-key-sentinel" in _render("searxng.env.j2")
    generators = [t for t in _tasks() if "searxng-secret-key" in str(t.get("ansible.builtin.shell", {}))]
    assert generators and all("creates" in t["ansible.builtin.shell"] for t in generators)


def test_a_settings_change_restarts_searxng() -> None:
    """The settings are a bind mount: Compose's hash never sees their content, so
    `up -d` alone would keep SearXNG on the old ones."""
    task = _template_task("searxng-settings.yml.j2")
    registered = task["register"]
    restarts = [
        t
        for t in _tasks()
        if "restart searxng" in str(t.get("ansible.builtin.command", "")) and registered in str(t.get("when", ""))
    ]
    assert restarts, "nothing restarts SearXNG when its settings change"


def test_open_webui_searches_through_searxng() -> None:
    env = _env()
    port = _search()["searxng"]["container_port"]
    assert env["ENABLE_WEB_SEARCH"] == "true"
    assert env["WEB_SEARCH_ENGINE"] == "searxng"
    assert env["SEARXNG_QUERY_URL"] == f"http://searxng:{port}/search"
    assert env["WEB_SEARCH_RESULT_COUNT"] == str(_search()["result_count"])
    # A regression guard, not evidence of the behaviour: v0.12.5 refuses
    # non-global addresses unless this is on (`retrieval/web/utils.py`,
    # `_assert_addresses_allowed`). Absent today; it must never be turned on.
    assert env.get("ENABLE_RAG_LOCAL_WEB_FETCH", "false") == "false"


def test_every_chat_starts_with_web_search_on() -> None:
    raw = _env()["DEFAULT_MODEL_METADATA"]
    assert "web_search" in json.loads(raw[1:-1])["defaultFeatureIds"]


def test_searxng_listens_on_the_port_open_webui_asks() -> None:
    """One key, both sides (#2970). The pinned image's server is granian, which
    reads GRANIAN_PORT (`container/Dockerfile`; SEARXNG_PORT is only an alias the
    entrypoint copies into it)."""
    port = _search()["searxng"]["container_port"]
    assert _searxng_service()["environment"]["GRANIAN_PORT"] == str(port)
    assert _env()["SEARXNG_QUERY_URL"].startswith(f"http://searxng:{port}/")


def _probe_tasks() -> list[dict]:
    """Scripts run inside Open WebUI's container, the script on stdin."""
    commands = [(t, t.get("ansible.builtin.command")) for t in _tasks()]
    return [
        t
        for t, cmd in commands
        if isinstance(cmd, dict) and "open-webui" in cmd.get("argv", []) and "lookup" in str(cmd.get("stdin", ""))
    ]


def test_every_service_with_no_port_is_probed_from_open_webui() -> None:
    """A service nobody can reach from outside is only checked from where its one
    client stands; without a probe, a dead one provisions as success (#2970)."""
    services = yaml.safe_load(_render("compose-webui.yml.j2"))["services"]
    unpublished = {name for name, svc in services.items() if "ports" not in svc}
    assert unpublished >= {"searxng"}, unpublished
    probed = " ".join(str(t["ansible.builtin.command"]["stdin"]) for t in _probe_tasks())
    for name in unpublished:
        assert f"{name}-probe.py" in probed, f"nothing probes {name}"


def test_the_search_probe_retries_and_needs_results() -> None:
    [task] = [t for t in _probe_tasks() if "searxng-probe.py" in str(t["ansible.builtin.command"]["stdin"])]
    assert task["retries"] >= 6
    assert "results" in task["until"]
    assert task["changed_when"] is False


def test_the_checks_run_whenever_open_webui_does() -> None:
    """The tests above find the probe in any task file; this holds the role to
    actually running it (#2970)."""
    from tests.test_agent_stack_role import ROLE

    main = yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))
    [step] = [t for t in main if t.get("ansible.builtin.import_tasks") == "webui_checks.yml"]
    assert step["when"] == "agent_stack_webui_configured | bool"
    assert "agent_stack" in step["tags"]
