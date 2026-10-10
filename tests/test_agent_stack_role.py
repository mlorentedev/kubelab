"""The agent_stack role: Open WebUI on ace2 (ADR-068, spec AI-009-hermes-ace2).

Rendered with the values `provision-ace2.yml` passes, read from `common.yaml`,
so a change to the SSOT is what these tests see, not a fixture's copy of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"
COMMON = REPO / "infra/config/values/common.yaml"

# ADR-068 D1: no single service on the dev node may take more than 1.5 GB.
MAX_MEMORY_BYTES = 1536 * 1024**2
SECRET_INPUTS = (
    "agent_stack_webui_oidc_client_secret",
    "agent_stack_webui_admin_password",
    "agent_stack_nan_api_key",
    "_agent_stack_webui_secret_key",
    "_agent_stack_hermes_api_key",
    "_agent_stack_mcp_bridge_key",
)
COMPOSE_FILES = ("compose-webui.yml.j2", "compose-hermes.yml.j2")
CONFIGURED = "agent_stack_webui_configured | bool"


def _common() -> dict:
    return yaml.safe_load(COMMON.read_text())


def _context() -> dict:
    common = _common()
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    return {
        **defaults,
        "ansible_managed": "managed",
        "tailscale_ip": common["networking"]["nodes"]["ace2"]["tailscale_ip"],
        "agent_stack_webui": common["apps"]["services"]["ai"]["open_webui"],
        "agent_stack_webui_oidc_client_id": "open-webui-oidc",
        "agent_stack_oidc_issuer": "https://auth.example.test",
        "agent_stack_webui_oidc_client_secret": "oidc-secret-sentinel",
        "agent_stack_webui_admin_email": "breakglass@example.test",
        "agent_stack_webui_admin_password": "admin-password-sentinel",
        "agent_stack_nan_api_key": "nan-key-sentinel",
        "_agent_stack_webui_secret_key": "session-key-sentinel",
        "agent_stack_agent_user": common["apps"]["services"]["ai"]["hermes_kubelab"]["user"],
        "agent_stack_hermes": common["apps"]["services"]["ai"]["hermes_kubelab"],
        "agent_stack_vault_zone": common["apps"]["services"]["ai"]["hermes_kubelab"]["vault_zone"],
        "agent_stack_headscale_url": f"https://{common['apps']['services']['core']['headscale']['domain']}",
        "agent_stack_deny_rules": yaml.safe_load((ROLE / "files/guardrails-denylist.yaml").read_text())["rules"],
        "_agent_stack_agent_uid": 999,
        "_agent_stack_hermes_api_key": "hermes-api-key-sentinel",
        "_agent_stack_mcp_bridge_key": "mcp-bridge-key-sentinel",
        "agent_stack_webui_bridge": common["networking"]["nodes"]["ace2"]["webui_bridge"],
    }


def _environment() -> Environment:
    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), undefined=StrictUndefined)
    # Ansible's: a rendered default is a string, and "False" is truthy to Jinja.
    env.filters["bool"] = lambda value: str(value).strip().lower() in ("true", "yes", "on", "1")
    return env


def _render(name: str) -> str:
    env = _environment()
    return env.get_template(name).render(**_resolved(env))


def _resolved(env: Environment, **overrides: object) -> dict:
    """The role's defaults are templates themselves, nested; Ansible resolves them
    lazily, so here each one is rendered from its template against the values of
    the previous pass until nothing changes. Rendering from the template, not from
    the previous result, is what lets a value that depends on another default see
    it resolved. A default that only Ansible can evaluate (a `lookup`) is left as
    written. `overrides` replace inputs before anything resolves, as extra vars do."""
    raw = {**_context(), **overrides}
    context = raw
    for _ in range(8):
        rendered = {k: _try_render(env, v, context) for k, v in raw.items()}
        if rendered == context:
            return context
        context = rendered
    raise AssertionError("the role's defaults do not resolve")


def _try_render(env: Environment, value: object, context: dict) -> object:
    if not isinstance(value, str) or "{{" not in value:
        return value
    try:
        return env.from_string(value).render(**context)
    except Exception:  # noqa: BLE001 - Ansible-only filters and lookups
        return value


def _tasks() -> list[dict]:
    """Every task in every file of the role, including those nested in a block."""
    flat: list[dict] = []
    for path in sorted((ROLE / "tasks").glob("*.yml")):
        for task in yaml.safe_load(path.read_text()) or []:
            flat.append(task)
            flat.extend(task.get("block") or [])
    return flat


def _template_task(src: str) -> dict:
    for task in _tasks():
        spec = task.get("ansible.builtin.template") or {}
        if spec.get("src") == src:
            return task
    raise AssertionError(f"no task renders {src}")


def _bytes(limit: str) -> int:
    units = {"k": 1024, "m": 1024**2, "g": 1024**3}
    limit = limit.strip().lower().removesuffix("b")
    return int(limit[:-1]) * units[limit[-1]] if limit[-1] in units else int(limit)


@pytest.mark.parametrize("compose_file", COMPOSE_FILES)
def test_every_service_is_memory_bounded_under_the_adr_limit(compose_file: str) -> None:
    compose = yaml.safe_load(_render(compose_file))
    for name, service in compose["services"].items():
        assert "mem_limit" in service, f"{name} has no memory limit"
        assert _bytes(str(service["mem_limit"])) <= MAX_MEMORY_BYTES, f"{name} exceeds ADR-068 D1's 1.5 GB"


def test_the_port_is_published_on_the_tailscale_address_only() -> None:
    """A bare `<port>:8080` listens everywhere, and ufw cannot restrict it (#959)."""
    ip = _context()["tailscale_ip"]
    compose = yaml.safe_load(_render("compose-webui.yml.j2"))
    for name, service in compose["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith(f"{ip}:"), f"{name} publishes {port!r} beyond the Tailscale address"


def test_the_env_file_is_private_and_never_logged() -> None:
    task = _template_task("webui.env.j2")
    assert task["ansible.builtin.template"]["mode"] == "0600"
    assert task["ansible.builtin.template"]["owner"] == "root"
    assert task.get("no_log") is True, "a diff of this file would print the OIDC secret"


@pytest.mark.parametrize("compose_file", COMPOSE_FILES)
@pytest.mark.parametrize("secret", SECRET_INPUTS)
def test_no_secret_reaches_the_compose_file(secret: str, compose_file: str) -> None:
    source = (ROLE / "templates" / compose_file).read_text()
    assert secret not in source
    assert _context()[secret] not in _render(compose_file)


def _env() -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in _render("webui.env.j2").splitlines() if line and not line.startswith("#")
    )


def test_sso_signs_up_and_the_form_admits_only_the_seeded_break_glass_account() -> None:
    """The form is the break-glass door (ADR-062 D4). Nobody can sign up through it.

    `ENABLE_LOGIN_FORM=false` would only hide the form: `/api/v1/auths/signin` keeps
    taking passwords (v0.11.4, lesson-520), so it never made SSO the only door.
    """
    env = _env()
    assert env["ENABLE_LOGIN_FORM"] == "true"
    assert env["ENABLE_SIGNUP"] == "false"
    assert env["ENABLE_OAUTH_SIGNUP"] == "true"
    assert env["OAUTH_MERGE_ACCOUNTS_BY_EMAIL"] == "false", "an SSO login must never adopt the local account"
    assert env["OAUTH_UPDATE_EMAIL_ON_LOGIN"] == "true", "auth-review keys accounts by the email Authelia sends"
    assert env["WEBUI_ADMIN_EMAIL"] == "breakglass@example.test"
    assert env["WEBUI_ADMIN_PASSWORD"] == "admin-password-sentinel"
    assert env["OAUTH_CLIENT_SECRET"] == "oidc-secret-sentinel"
    assert env["ENABLE_OLLAMA_API"] == "false"


def test_tiers_come_from_authelia_groups_and_anyone_else_is_refused() -> None:
    """ADR-062 D2: `admins` is admin, `users` is user; a login with neither gets a 403."""
    env = _env()
    assert env["ENABLE_OAUTH_ROLE_MANAGEMENT"] == "true"
    assert env["OAUTH_ROLES_CLAIM"] == "groups"
    assert env["OAUTH_ADMIN_ROLES"] == "admins"
    assert set(env["OAUTH_ALLOWED_ROLES"].split(",")) == {"users", "admins"}


def test_userinfo_is_always_read_because_authelia_sends_groups_only_there() -> None:
    """lesson-457: groups are in UserInfo, not the ID token. Open WebUI v0.11.4 calls
    UserInfo only when the ID token lacks the email or the username claim, so the
    username claim is one Authelia keeps out of the ID token."""
    assert _env()["OAUTH_USERNAME_CLAIM"] == "preferred_username"


def test_the_env_file_is_the_configuration_of_record() -> None:
    """With persistent config on, env only seeds the first start and a later edit is a silent no-op."""
    assert _env()["ENABLE_PERSISTENT_CONFIG"] == "false"


def test_open_webui_is_not_deployed_without_an_oidc_secret_and_a_break_glass_password() -> None:
    """With the form on and an empty database, the first visitor to sign up becomes admin
    (`auths.py` gates the first signup on neither ENABLE_SIGNUP nor anything else). The
    seeded break-glass account is what closes that, so no seed, no start."""
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    gate = defaults["agent_stack_webui_configured"]
    assert "agent_stack_webui_oidc_client_secret | length > 0" in gate
    assert "agent_stack_webui_admin_password | length > 0" in gate
    [block] = [t for t in _tasks() if t.get("name") == "Deploy Open WebUI"]
    assert block["when"] == CONFIGURED


def test_the_seeded_account_is_proved_to_be_the_admin_after_every_start() -> None:
    [check] = [t for t in _tasks() if t.get("name") == "Verify the break-glass account is the seeded admin"]
    spec = check["ansible.builtin.uri"]
    assert spec["url"].endswith("/api/v1/auths/signin") and spec["method"] == "POST"
    assert check.get("no_log") is True, "the request body carries the password"
    assert "admin" in str(check["failed_when"])


def test_the_redirect_uri_is_the_public_name_the_client_registers() -> None:
    """Behind Traefik, Open WebUI sees plain HTTP and would build an `http://`
    redirect that Authelia refuses, so the one registered URI is set (#2135)."""
    webui = _context()["agent_stack_webui"]
    env = _env()
    base = f"https://{webui['domain']}"
    assert env["WEBUI_URL"] == base
    assert env["OPENID_REDIRECT_URI"] == f"{base}/oauth/oidc/callback"


def test_the_role_runs_on_ace2_after_dev_node() -> None:
    plays = yaml.safe_load((REPO / "infra/ansible/playbooks/provision-ace2.yml").read_text())
    roles = [r["role"].rsplit("/", 1)[-1] for r in plays[1]["roles"]]
    assert "agent_stack" in roles
    assert roles.index("agent_stack") > roles.index("dev_node")


def test_open_webui_reads_the_one_nan_key_pr_agent_uses() -> None:
    """R1 (operator, 2026-10-04): one NaN key in the vault, read where it lives; no second vault path."""
    from toolkit.features.secrets_manager import SECRET_CATALOG

    key = "apps.services.automation.pr_agent.nan_api_key"
    plays = yaml.safe_load((REPO / "infra/ansible/playbooks/provision-ace2.yml").read_text())
    [stack] = [r for r in plays[1]["roles"] if r["role"].endswith("agent_stack")]
    # Prod's vault: the key is registered `envs=("prod",)`, and `secrets` here is staging's.
    assert stack["vars"]["agent_stack_nan_api_key"] == "{{ gitea_secrets." + key + " | default('') }}"
    [spec] = [s for s in SECRET_CATALOG if s.key_path == key]
    for consumer in ("open_webui", "hermes_kubelab"):
        assert consumer in spec.services, "a rotation must name every consumer, or ace2 keeps the old key"
    # Key names are plaintext in SOPS, so the vault itself is read: an unregistered
    # copy (the old `open_webui.nan_api_key` path) would escape the catalog and the
    # audit. A second key that Hermes's R1 may mint is fine once it is registered;
    # what fails is a NaN key the catalog does not know, or one stored in a vault
    # its spec does not cover (common merges into every env, so it covers all).
    specs = {s.key_path: s for s in SECRET_CATALOG}
    stray = sorted(
        f"{store.name}:{path}"
        for store in sorted((REPO / "infra/config/secrets").glob("*.enc.yaml"))
        for path in _key_paths(yaml.safe_load(store.read_text()))
        if path.endswith(".nan_api_key")
        and not (path in specs and store.name.split(".")[0] in ("common", *specs[path].envs))
    )
    assert not stray, f"a NaN key outside the catalog, or in a vault its spec does not cover: {stray}"
    assert key in _key_paths(yaml.safe_load((REPO / "infra/config/secrets/prod.enc.yaml").read_text()))


def _key_paths(node: object, prefix: str = "") -> list[str]:
    if not isinstance(node, dict):
        return [prefix]
    return [p for k, v in node.items() if k != "sops" for p in _key_paths(v, f"{prefix}.{k}" if prefix else k)]


def test_an_unconfigured_run_takes_a_previous_open_webui_down() -> None:
    """Removing the secret from SOPS must stop Open WebUI, not leave it serving."""
    [stop] = [t for t in _tasks() if t.get("name") == "Stop Open WebUI when it is not configured"]
    assert stop["when"] == "not (" + CONFIGURED + ")"
    commands = [t["ansible.builtin.command"] for t in stop["block"] if "ansible.builtin.command" in t]
    assert any(c.rstrip().endswith(" down") for c in commands)
    [remove] = [t for t in stop["block"] if "ansible.builtin.file" in t]
    assert "webui.env" in remove["loop"], "the secret-bearing env file must not outlive the service"


def test_the_container_resolves_through_magicdns_first() -> None:
    """Docker never passes the host's 100.100.100.100 in; a public resolver alone cannot see the tailnet."""
    compose = yaml.safe_load(_render("compose-webui.yml.j2"))
    dns = compose["services"]["open-webui"]["dns"]
    assert dns == _context()["agent_stack_docker_dns_servers"]
    assert dns[0] == "100.100.100.100", dns


def test_only_open_webuis_own_origin_may_read_it_with_credentials() -> None:
    """v0.11.4 defaults `CORS_ALLOW_ORIGIN` to `*` and passes it to Starlette with
    `allow_credentials=True`, which echoes any origin back on a request with a cookie,
    and socket.io accepts the upgrade from any origin (#2109, measured live). `.internal`
    is on no public suffix list, so every `*.kubelab.internal` host is the same site."""
    webui = _context()["agent_stack_webui"]
    env = _env()
    direct = f"{webui['scheme']}://{webui['host']}:{webui['default_port']}"
    # People at the public name, break-glass at ace2's own address (#2135).
    assert env["CORS_ALLOW_ORIGIN"].split(";") == [env["WEBUI_URL"], direct]
    assert "*" not in env["CORS_ALLOW_ORIGIN"]


def test_every_generated_key_survives_a_fresh_nodes_dry_run() -> None:
    """A dry run skips the `openssl` that writes each key, so on a node that never
    had one there is nothing to slurp. The read must not fail the dry run."""
    reads = [t for t in _tasks() if "ansible.builtin.slurp" in t and "key" in t["ansible.builtin.slurp"]["src"]]
    assert len(reads) >= 3
    for task in reads:
        assert task.get("ignore_errors") == "{{ ansible_check_mode }}", task["name"]
