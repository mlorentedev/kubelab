"""The role-owned NaN image provider enforces a real shared monthly budget.

The pinned Hermes OpenAI provider has no monthly quota key. These tests load the
role's plugin with small upstream stubs, then exercise its persistent counter and
backend boundary; no NaN credential or live image is needed for the red/green loop.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent / "infra/ansible/roles/agent_stack/files/hermes-plugins/nan/__init__.py"


class _Backend:
    calls: list[str] = []

    def generate(self, prompt: str, aspect_ratio: str = "landscape", **_: object) -> dict:
        self.calls.append(prompt)
        return {"success": True, "provider": "openai", "model": "flux-2-klein", "prompt": prompt}


@pytest.fixture
def plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Do not leave bytecode inside the Ansible role: repository-wide role
    # contracts iterate every shipped file and generated .pyc is not UTF-8.
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    _Backend.calls = []
    openai = types.ModuleType("plugins.image_gen.openai")
    openai.OpenAIImageGenProvider = _Backend
    common = types.ModuleType("plugins.image_gen._common")
    common.load_image_gen_config = lambda _name: {}
    provider_base = types.ModuleType("agent.image_gen_provider")
    provider_base.error_response = lambda **kwargs: {"success": False, **kwargs}
    constants = types.ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: tmp_path
    modules = {
        "agent": types.ModuleType("agent"),
        "hermes_constants": constants,
        "plugins": types.ModuleType("plugins"),
        "plugins.image_gen": types.ModuleType("plugins.image_gen"),
        "plugins.image_gen.openai": openai,
        "plugins.image_gen._common": common,
        "agent.image_gen_provider": provider_base,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("nan_image_provider_under_test", PLUGIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._load_image_gen_config = lambda _name: {"monthly_limit": 2, "monthly_shared_limit": 100}
    module._utc_month = lambda: "2026-11"
    return module


def test_both_nan_models_are_declared_with_flux_as_default(plugin) -> None:
    provider = plugin.NaNImageGenProvider()
    assert provider.provider_id == "nan"
    assert provider.default_model_id == "flux-2-klein"
    assert list(provider.models) == ["flux-2-klein", "qwen-image-2.1"]


def test_the_shared_counter_refuses_the_next_request_without_calling_nan(plugin, tmp_path: Path) -> None:
    plugin._load_image_gen_config = lambda _name: {"monthly_limit": 1, "monthly_shared_limit": 100}
    provider = plugin.NaNImageGenProvider()
    first = provider.generate("first")
    second = provider.generate("second")
    assert first["success"] is True
    assert first["provider"] == "nan"  # do not mislabel the inherited OpenAI transport as the backend
    assert first["nan_monthly_remaining"] == 0
    assert second["success"] is False
    assert second["error_type"] == "quota_exceeded"
    assert second["nan_monthly_remaining"] == 0
    assert _Backend.calls == ["first"]
    state = json.loads((tmp_path / "cache/nan-image-quota.json").read_text(encoding="utf-8"))
    assert state == {"month": "2026-11", "used": 1}


def test_flux_and_qwen_draw_from_the_same_counter(plugin) -> None:
    quota = plugin.MonthlyImageQuota(limit=2)
    assert quota.claim() == 1  # flux
    assert quota.claim() == 0  # qwen: same member-wide pool, never a second budget
    with pytest.raises(plugin.QuotaExceeded):
        quota.claim()


def test_a_new_utc_month_starts_a_new_budget(plugin) -> None:
    quota = plugin.MonthlyImageQuota(limit=1)
    assert quota.claim() == 0
    quota._month = lambda: "2026-12"
    assert quota.claim() == 0


def test_corrupt_state_fails_closed_without_calling_nan(plugin, tmp_path: Path) -> None:
    state = tmp_path / "cache/nan-image-quota.json"
    state.parent.mkdir(parents=True)
    state.write_text("not json", encoding="utf-8")
    result = plugin.NaNImageGenProvider().generate("must not run")
    assert result["success"] is False
    assert result["error_type"] == "quota_unavailable"
    assert _Backend.calls == []


def test_parallel_calls_cannot_cross_the_cap(plugin) -> None:
    plugin._load_image_gen_config = lambda _name: {"monthly_limit": 5, "monthly_shared_limit": 100}
    provider = plugin.NaNImageGenProvider()
    results = list(ThreadPoolExecutor(max_workers=10).map(lambda n: provider.generate(f"image {n}"), range(10)))
    assert sum(bool(r["success"]) for r in results) == 5
    assert sum(r.get("error_type") == "quota_exceeded" for r in results) == 5
    assert len(_Backend.calls) == 5


def test_the_plugin_source_contains_no_credential(plugin) -> None:
    source = PLUGIN.read_text(encoding="utf-8")
    assert "nan-key-sentinel" not in source
    assert "print(" not in source, "quota state and configuration must not be logged blindly"
