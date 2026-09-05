"""Tests for sync_branding — IDP brand design system tokens (ADR-032).

Verifies that branding tokens declared in common.yaml SSOT are deterministically
projected into master brand CSS (edge/errors/html/brand/brand.css) and that drift
detection operates correctly.
"""

from __future__ import annotations

from pathlib import Path

from toolkit.cli.sync import _run_with_check
from toolkit.scripts import sync_branding


class TestGenerateBrandCss:
    def test_renders_tokens_correctly(self) -> None:
        branding = {
            "palette": {
                "primary": "#123456",
                "primary_hover": "#234567",
                "accent": "#345678",
                "accent_light": "#456789",
                "bg_dark": "#111111",
                "surface_dark": "#222222",
                "surface_hover": "#333333",
                "border_dark": "rgba(255, 255, 255, 0.1)",
                "text_primary": "#FFFFFF",
                "text_secondary": "#CCCCCC",
                "text_muted": "#888888",
            },
            "typography": {
                "font_sans": "CustomSans, sans-serif",
                "font_mono": "CustomMono, monospace",
            },
        }
        css = sync_branding.generate_brand_css(branding)
        assert "--kl-primary: #123456;" in css
        assert "--kl-primary-hover: #234567;" in css
        assert "--kl-accent: #345678;" in css
        assert "--kl-bg-dark: #111111;" in css
        assert "--kl-font-sans: CustomSans, sans-serif;" in css
        assert "--kl-font-mono: CustomMono, monospace;" in css

    def test_falls_back_to_defaults_when_empty(self) -> None:
        css = sync_branding.generate_brand_css({})
        assert f"--kl-primary: {sync_branding.DEFAULT_PALETTE['primary']};" in css
        assert f"--kl-bg-dark: {sync_branding.DEFAULT_PALETTE['bg_dark']};" in css


class TestBrandingSyncLive:
    def test_sync_branding_writes_expected_css(self, tmp_path: Path, monkeypatch) -> None:
        test_css = tmp_path / "brand.css"
        monkeypatch.setattr(sync_branding, "OUTPUT_CSS", test_css)
        rc = sync_branding.main()
        assert rc == 0
        assert test_css.exists()
        content = test_css.read_text(encoding="utf-8")
        assert "--kl-primary: #0E7490;" in content
        assert "--kl-accent: #3F51B5;" in content

    def test_committed_brand_css_matches_common_yaml(self) -> None:
        """The committed brand.css must match common.yaml without running a sync first."""
        assert sync_branding.OUTPUT_CSS.exists()
        in_sync = _run_with_check([sync_branding.OUTPUT_CSS], sync_branding.main, "branding")
        assert in_sync is True

    def test_drift_check_detects_mutation(self, tmp_path: Path, monkeypatch) -> None:
        """Drift check returns False when the target CSS diverges from common.yaml."""
        test_css = tmp_path / "brand.css"
        test_css.write_text("/* drifted content */\n:root { --drift: true; }\n", encoding="utf-8")
        monkeypatch.setattr(sync_branding, "OUTPUT_CSS", test_css)
        in_sync = _run_with_check([test_css], sync_branding.main, "branding")
        assert in_sync is False

    def test_returns_error_when_yaml_missing(self, tmp_path: Path, monkeypatch) -> None:
        non_existent = tmp_path / "missing.yaml"
        monkeypatch.setattr(sync_branding, "COMMON_YAML", non_existent)
        rc = sync_branding.main()
        assert rc == 1
