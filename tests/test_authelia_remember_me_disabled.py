"""#1813: Authelia offers no "remember me", in every environment.

With it, a session lived a month, and fasthttp/session refreshes the cookie's expiry
on every save, so an active browser never reached the end of it. That outlived the 8h
the platform declares for a session and everything that follows from it (sign-out,
group demotion, app lifetimes bounded by the IdP). The owner chose to disable it
(2026-10-17, #1813). Authelia disables the option with `-1`.

The check reads what each environment runs: the EMITTED authelia-config for the K8s
overlays (prod's uses `behavior: replace` and inherits nothing from the base file),
and the dev configuration rendered from the template with the loader's real values.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, Undefined

from toolkit.config.constants import AUTHELIA_CONFIG
from toolkit.features.configuration import ConfigurationManager

ROOT = Path(__file__).resolve().parents[1]
DISABLED = -1


@pytest.mark.parametrize("overlay", ("staging", "prod"))
def test_the_emitted_config_disables_remember_me(overlay: str) -> None:
    if shutil.which("kubectl") is None:
        pytest.skip(f"kubectl not on PATH: the {overlay} Authelia config was NOT checked")
    out = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "infra/k8s/overlays" / overlay)], capture_output=True, text=True, check=True
    ).stdout
    config = next(
        d
        for d in yaml.safe_load_all(out)
        if d and d.get("kind") == "ConfigMap" and d["metadata"]["name"].startswith("authelia-config")
    )
    session = yaml.safe_load(config["data"]["configuration.yml"])["session"]
    assert session["remember_me"] == DISABLED, f"{overlay}: remember_me is {session['remember_me']!r}"


class _SopsPlaceholder(Undefined):
    """Stands in for values only SOPS holds; the setting under test is not one of them."""

    def __str__(self) -> str:
        return "unset-secret"


def test_the_rendered_dev_config_disables_remember_me(monkeypatch: pytest.MonkeyPatch) -> None:
    """Renders the dev template from the loader's values, so a broken mapping fails here."""
    manager = ConfigurationManager("dev", ROOT)
    monkeypatch.setattr(manager, "_decrypt_sops", lambda _path: {})
    context = {
        **manager.get_env_vars(),
        "apps": [],
        "authelia_users": [],
        "trusted_cidrs": [],
        "oidc_clients": [],
        **{name: getattr(AUTHELIA_CONFIG, name) for name in dir(AUTHELIA_CONFIG) if name.startswith("ARGON2_")},
    }
    templates = Environment(
        loader=FileSystemLoader(ROOT / "infra/config/authelia/templates"), undefined=_SopsPlaceholder
    )
    rendered = yaml.safe_load(templates.get_template("configuration.yml.j2").render(context))
    assert rendered["session"]["remember_me"] == DISABLED, f"dev: remember_me is {rendered['session']['remember_me']!r}"
