"""NaN image generation with a local, shared monthly request budget.

Wraps Hermes v0.22.1's OpenAI-compatible provider. NaN documents one 100-request
member/month pool shared by flux and qwen; this provider admits only the smaller
Hermes budget so Open WebUI keeps headroom. State and locks live in the gateway's
cache, never in the vault. A claim is consumed before dispatch because NaN may
meter failed requests too; this deliberately fails conservative.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.image_gen_provider import error_response
from hermes_constants import get_hermes_home
from plugins.image_gen._common import load_image_gen_config as _load_image_gen_config
from plugins.image_gen.openai import OpenAIImageGenProvider


def _utc_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


class QuotaExceeded(Exception):
    """The local Hermes budget is exhausted for the current UTC month."""

    def __init__(self, month: str, limit: int) -> None:
        super().__init__(month, limit)
        self.month = month
        self.limit = limit


class MonthlyImageQuota:
    """Locked, atomic request counter shared by every NaN image model."""

    def __init__(self, limit: int, path: Path | None = None) -> None:
        if limit <= 0:
            raise ValueError("the monthly image limit must be positive")
        self.limit = limit
        self.path = path or get_hermes_home() / "cache/nan-image-quota.json"
        self._month = _utc_month

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"month": self._month(), "used": 0}
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("the NaN image quota state is unreadable") from exc
        if (
            not isinstance(state, dict)
            or set(state) != {"month", "used"}
            or not isinstance(state["month"], str)
            or len(state["month"]) != 7
            or state["month"][4] != "-"
            or not state["month"].replace("-", "").isdigit()
            or not isinstance(state["used"], int)
            or isinstance(state["used"], bool)
            or state["used"] < 0
        ):
            raise ValueError("the NaN image quota state is invalid")
        return state if state["month"] == self._month() else {"month": self._month(), "used": 0}

    def _write(self, state: dict[str, Any]) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".nan-image-quota-", dir=self.path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def claim(self) -> int:
        """Consume one request and return remaining calls, all under one lock."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self._read()
            if state["used"] >= self.limit:
                raise QuotaExceeded(state["month"], self.limit)
            state["used"] += 1
            self._write(state)
            return self.limit - state["used"]


class NaNImageGenProvider(OpenAIImageGenProvider):
    """The pinned OpenAI provider plus NaN's member-wide monthly guardrail."""

    provider_id = "nan"
    label = "NaN"
    models = {
        "flux-2-klein": {"display": "FLUX 2 Klein", "strengths": "Fast generation and image editing"},
        "qwen-image-2.1": {"display": "Qwen Image 2.1", "strengths": "Prompt adherence and text rendering"},
    }
    default_model_id = "flux-2-klein"
    price = "Hermes budget: 50 requests/month shared by both models"
    setup = {"name": "NaN", "badge": "quota", "tag": "Shared monthly image budget", "key": "NAN_API_KEY"}

    def _quota(self) -> MonthlyImageQuota:
        config = _load_image_gen_config("nan")
        limit = int(config.get("monthly_limit", 50))
        shared = int(config.get("monthly_shared_limit", 100))
        if not 0 < limit <= shared:
            raise ValueError("the Hermes image limit must be between 1 and NaN's shared cap")
        return MonthlyImageQuota(limit)

    def generate(self, prompt: str, aspect_ratio: str = "landscape", **kwargs: Any) -> dict[str, Any]:
        try:
            remaining = self._quota().claim()
        except QuotaExceeded as exc:
            result = error_response(
                error=f"NaN image budget exhausted for {exc.month}: {exc.limit} Hermes requests used; "
                "the remaining member allowance is reserved for Open WebUI.",
                error_type="quota_exceeded", provider="nan", prompt=prompt, aspect_ratio=aspect_ratio,
            )
            remaining = 0
        except (OSError, ValueError) as exc:
            return error_response(
                error=f"NaN image quota is unavailable; refusing the request without calling the backend: {exc}",
                error_type="quota_unavailable", provider="nan", prompt=prompt, aspect_ratio=aspect_ratio,
            )
        else:
            result = super().generate(prompt, aspect_ratio, **kwargs)
        # OpenAI is only the transport; report the selected backend accurately.
        result["provider"] = "nan"
        result["nan_monthly_remaining"] = remaining
        return result


def register(ctx) -> None:
    """Register the opt-in provider with Hermes's image backend registry."""
    ctx.register_image_gen_provider(NaNImageGenProvider())
