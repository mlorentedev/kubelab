"""apps/console ships as its own image (ADR-074 D1, D3), and four things have to hold for that
to be a delivery and not a directory.

* nginx serves what Traefik's `secure-headers` would, because through the ingress the edge's
  values replace the origin's and a divergence is invisible from outside (the same reason
  `web` holds the equality).
* A hashed asset is cached for good and nothing else is: the page names those hashes, so a
  stale page would point at files a new build no longer ships.
* The release package is complete: release-please treats a package with no manifest entry as
  new, and a `version.txt` that disagrees with the manifest is what it reads next.
* CI builds the app when it changes, and runs the Go test that holds its fixtures to the API
  handler. That test lives in `apps/api`, whose job is gated on `apps/api/**`, so an edit to the
  fixtures alone reaches master without it unless the console job runs it too.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "apps/console"
NGINX = (CONSOLE / "nginx.conf").read_text(encoding="utf-8")
CODE = re.sub(r"#.*", "", NGINX)  # the file's comments name `location` and `add_header` too
CI = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
PIPELINE = yaml.safe_load((ROOT / ".github/workflows/ci-pipeline.yml").read_text(encoding="utf-8"))


def _add_headers() -> dict[str, str]:
    """The `add_header` lines of the server block, name to literal value."""
    return {m.group(1): m.group(2) for m in re.finditer(r'^\s*add_header\s+(\S+)\s+"([^"]*)"\s+always;', NGINX, re.M)}


def _map(name: str) -> dict[str, str]:
    """A `map $x $name { pattern value; }` block, pattern to value."""
    block = re.search(r"map\s+\$\w+\s+\$%s\s*\{(.*?)\n\}" % re.escape(name), NGINX, re.S)
    assert block, f"no `map ... ${name}` in apps/console/nginx.conf"
    out: dict[str, str] = {}
    for line in block.group(1).splitlines():
        m = re.match(r'\s*(\S+)\s+("[^"]*"|\$\w+)\s*;', line)
        if m:
            out[m.group(1)] = m.group(2).strip('"')
    return out


class TestSecurityHeaders:
    def test_nginx_sends_what_the_edge_middleware_declares(self) -> None:
        mw = yaml.safe_load((ROOT / "infra/k8s/base/edge/secure-headers.yaml").read_text(encoding="utf-8"))["spec"][
            "headers"
        ]
        want = {"Referrer-Policy": mw["referrerPolicy"], "Permissions-Policy": mw["permissionsPolicy"]}
        if mw["contentTypeNosniff"]:
            want["X-Content-Type-Options"] = "nosniff"
        if mw["frameDeny"]:
            want["X-Frame-Options"] = "DENY"
        got = _add_headers()
        assert {k: got.get(k) for k in want} == want

    def test_headers_are_not_dropped_by_a_location(self) -> None:
        """An `add_header` inside a `location` replaces the server-level set for that path."""
        blocks = re.findall(r"^\s*location\b[^{]*\{(.*?)\n    \}", CODE, re.S | re.M)
        assert blocks, "no location block parsed: the guard would pass over nothing"
        for body in blocks:
            assert "add_header" not in body


class TestCachePolicy:
    def test_only_content_hashed_assets_are_immutable(self) -> None:
        paths = _map("path_cache_control")
        assert paths["~^/_astro/"] == "public, max-age=31536000, immutable"
        assert paths["default"] == "no-cache"
        immutable = [k for k, v in paths.items() if "immutable" in v]
        assert immutable == ["~^/_astro/"]

    def test_an_error_revalidates_whatever_its_path(self) -> None:
        assert _map("cache_control")["~^[45]"] == "no-cache"
        assert re.search(r"add_header\s+Cache-Control\s+\$cache_control\s+always;", NGINX)


class TestReleasePackage:
    CONFIG = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    MANIFEST = json.loads((ROOT / ".release-please-manifest.json").read_text(encoding="utf-8"))

    def test_every_package_has_a_manifest_entry(self) -> None:
        assert set(self.CONFIG["packages"]) == set(self.MANIFEST)

    def test_the_console_is_a_package_with_its_own_tag_line(self) -> None:
        pkg = self.CONFIG["packages"]["apps/console"]
        assert pkg == {"release-type": "simple", "component": "console"}
        assert self.CONFIG["include-component-in-tag"] is True

    def test_version_txt_agrees_with_the_manifest(self) -> None:
        for path, version in self.MANIFEST.items():
            assert (ROOT / path / "version.txt").read_text(encoding="utf-8").strip() == version, path


class TestCiBuildsTheConsole:
    def test_a_change_under_the_app_starts_its_pipeline(self) -> None:
        detect = CI["jobs"]["detect-changes"]
        filters = yaml.safe_load(
            next(s for s in detect["steps"] if s.get("id") == "filter")["with"]["filters"]  # type: ignore[index]
        )
        assert filters["console"] == ["apps/console/**"]
        job = CI["jobs"]["console-pipeline"]
        assert job["uses"] == "./.github/workflows/ci-pipeline.yml"
        assert job["with"]["app"] == "console"
        assert "outputs.console" in job["if"]

    def test_the_pipeline_builds_the_app_directory_as_the_image_context(self) -> None:
        step = next(s for s in PIPELINE["jobs"]["app-pipeline"]["steps"] if s.get("id") == "context")
        assert re.search(r"console\)\s*\n\s*echo \"context=\./apps/console\"", step["run"])
        assert (CONSOLE / "Dockerfile").is_file()

    def test_the_console_job_runs_the_go_test_that_holds_its_fixtures(self) -> None:
        steps = PIPELINE["jobs"]["app-pipeline"]["steps"]
        step = next(s for s in steps if "fixtures still match" in s.get("name", ""))
        assert "inputs.app == 'console'" in step["if"]
        run = step["run"]
        assert "TestFixturesMatchTheQueueContract" in run
        # `go test -run` exits 0 when it matches nothing, so the step must also read the PASS line.
        assert re.search(r"grep -q .*--- PASS: TestFixturesMatchTheQueueContract", run)
        assert step["working-directory"] == "./apps/api/src"

    def test_that_go_test_exists_under_the_name_the_step_asks_for(self) -> None:
        src = (ROOT / "apps/api/src/internal/console/fixtures_test.go").read_text(encoding="utf-8")
        assert "func TestFixturesMatchTheQueueContract(" in src

    def test_the_console_unit_suite_runs(self) -> None:
        steps = PIPELINE["jobs"]["app-pipeline"]["steps"]
        step = next(s for s in steps if s.get("name") == "Test console code")
        assert step["run"] == "npm test"
        assert step["working-directory"] == "./apps/console"


def test_dependabot_tracks_the_console_base_images() -> None:
    cfg = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
    declared = {(u["package-ecosystem"], u["directory"]) for u in cfg["updates"]}
    assert ("docker", "/apps/console") in declared
    assert ("npm", "/apps/console") in declared


def test_a_console_fix_cannot_release_before_there_is_a_job_to_publish_it() -> None:
    """release-please puts every releasable package in one pull request. A `fix` commit under
    apps/console would add `console-vX.Y.Z` to the next `api` release, and until `release.yml`
    re-tags an image for it that tag names nothing. Dependabot writes such commits, so its
    prefix for the app is `chore` until the publish job exists."""
    release = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    if "publish-console" in release["jobs"]:
        return
    cfg = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
    prefixes = {
        u["commit-message"]["prefix"] for u in cfg["updates"] if u["directory"] == "/apps/console" and "commit-message" in u
    }
    assert prefixes == {"chore"}, f"console dependency commits would release without a publish job: {prefixes}"
