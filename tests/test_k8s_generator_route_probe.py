"""GITOPS-003 AC3: a `PostSync` hook probes each same-origin route it declares.

A merge is not a deploy, and a Synced Application is not a working route: the
newsletter form posted to `/api/subscribe` on the web host and reached the static
site for months (kubelab#774) while Argo CD reported everything green. The probe
sends the request the form sends and fails the sync unless the API answers it.

Three layers, each checked where it can fail: the SSOT entry reaches the route
dict, the overlays emit the Job Argo CD runs (read from `kubectl kustomize`, never
the template), and the Job's own script judges an answer the way it should.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import stat
import subprocess
from typing import Any

import pytest
import yaml

from toolkit.features.generator_k8s import K8sGenerator

REPO = pathlib.Path(__file__).resolve().parent.parent

PROBE = {
    "method": "POST",
    "path": "/api/subscribe",
    "body": "{",
    "expect_status": 400,
    "expect_content_type": "text/plain",
}
WEB_ENV = {
    "APPS_PLATFORM_WEB_EXTRA_ROUTES": [{"path_prefix": "/api", "service": "api", "probe": PROBE}],
    "APPS_PLATFORM_API_DEFAULT_PORT": "8080",
}
HOSTS = {"staging": "staging.mlorente.dev", "prod": "mlorente.dev"}


class TestBuildExtraRoutesProbe:
    def test_probe_is_carried_from_the_ssot_entry(self) -> None:
        (route,) = K8sGenerator()._build_extra_routes(WEB_ENV, "web")

        assert route["probe"] == {**PROBE, "name": "web-route-probe-api"}

    def test_route_without_probe_has_no_probe_key(self) -> None:
        env = {**WEB_ENV, "APPS_PLATFORM_WEB_EXTRA_ROUTES": [{"path_prefix": "/api", "service": "api"}]}

        (route,) = K8sGenerator()._build_extra_routes(env, "web")

        assert "probe" not in route

    def test_probe_missing_an_expectation_is_refused(self) -> None:
        """A probe that expects nothing would pass on any answer, nginx's included."""
        broken = {k: v for k, v in PROBE.items() if k != "expect_content_type"}
        env = {**WEB_ENV, "APPS_PLATFORM_WEB_EXTRA_ROUTES": [{"path_prefix": "/api", "service": "api", "probe": broken}]}

        with pytest.raises(ValueError, match="expect_content_type"):
            K8sGenerator()._build_extra_routes(env, "web")


def test_template_renders_routes_without_a_probe(tmp_path: pathlib.Path) -> None:
    """The renderer is StrictUndefined: a route lacking `probe` must render nothing, not raise."""
    from toolkit.core.templating import create_renderer

    out = tmp_path / "hooks.yaml"
    context = {
        "namespace": "kubelab",
        "route_probe_image": "curlimages/curl:8.11.1",
        "apps": [{"name": "web", "domain": "x", "extra_routes": [{"path_prefix": "/api", "service": "api"}]}],
    }

    assert create_renderer(REPO / "infra/k8s/templates").render_template("hooks.yaml.j2", out, context)
    assert not [d for d in yaml.safe_load_all(out.read_text()) if d]


def _render(overlay: str) -> list[dict[str, Any]]:
    if shutil.which("kubectl") is None:
        if os.environ.get("CI"):
            pytest.fail("kubectl not on PATH in CI: the route probe went unchecked")
        pytest.skip("kubectl not on PATH: cannot render the overlays (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / overlay)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def _probe_job(overlay: str) -> dict[str, Any]:
    jobs = [d for d in _render(overlay) if d["kind"] == "Job" and d["metadata"]["name"] == "web-route-probe-api"]
    assert len(jobs) == 1, f"{overlay} renders {len(jobs)} web-route-probe-api Jobs"
    return jobs[0]


def _env(job: dict[str, Any]) -> dict[str, str]:
    (container,) = job["spec"]["template"]["spec"]["containers"]
    return {e["name"]: e["value"] for e in container["env"]}


@pytest.mark.parametrize("overlay", ["staging", "prod"])
class TestRenderedHook:
    def test_is_a_postsync_hook_kept_only_when_it_fails(self, overlay: str) -> None:
        annotations = _probe_job(overlay)["metadata"]["annotations"]

        assert annotations["argocd.argoproj.io/hook"] == "PostSync"
        # BeforeHookCreation must stay: declaring HookSucceeded alone drops Argo's
        # default, and a kept failed Job then blocks every later sync by name.
        assert set(annotations["argocd.argoproj.io/hook-delete-policy"].split(",")) == {
            "BeforeHookCreation",
            "HookSucceeded",
        }

    def test_targets_the_env_host_through_traefik(self, overlay: str) -> None:
        env = _env(_probe_job(overlay))

        assert env["PROBE_HOST"] == HOSTS[overlay]
        assert env["PROBE_CONNECT_TO"] == "traefik.kube-system.svc:443"
        assert (env["PROBE_METHOD"], env["PROBE_PATH"], env["PROBE_BODY"]) == ("POST", "/api/subscribe", "{")
        assert (env["EXPECT_STATUS"], env["EXPECT_CONTENT_TYPE"]) == ("400", "text/plain")

    def test_runs_once_and_bounded(self, overlay: str) -> None:
        spec = _probe_job(overlay)["spec"]

        assert spec["backoffLimit"] == 0
        assert spec["activeDeadlineSeconds"] <= 120
        # A failed Job kept by the delete policy must not block `make deploy-k8s`
        # for ever: a Job's spec is immutable, so a changed template fails the apply.
        assert spec["ttlSecondsAfterFinished"] <= 86400

    def test_has_an_ingress_networkpolicy(self, overlay: str) -> None:
        labels = _probe_job(overlay)["spec"]["template"]["metadata"]["labels"]
        policies = [
            d
            for d in _render(overlay)
            if d["kind"] == "NetworkPolicy"
            and "Ingress" in d["spec"]["policyTypes"]
            and d["spec"]["podSelector"].get("matchLabels", {}).items() <= labels.items()
            and not d["spec"].get("ingress")
        ]

        assert policies, "the probe pod has no deny-all Ingress NetworkPolicy"


def _run_script(tmp_path: pathlib.Path, answer: str) -> tuple[int, str, str]:
    """Run the Job's own script with a stub `curl` that answers `answer`."""
    job = _probe_job("staging")
    (container,) = job["spec"]["template"]["spec"]["containers"]
    assert container["command"][:2] == ["/bin/sh", "-c"]
    stub = tmp_path / "curl"
    stub.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$@" > "{tmp_path}/args"\nprintf \'%s\' \'{answer}\'\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {**_env(job), "PATH": f"{tmp_path}:/usr/bin:/bin"}
    proc = subprocess.run(["/bin/sh", "-c", container["command"][2]], env=env, capture_output=True, text=True)
    args = (tmp_path / "args").read_text() if (tmp_path / "args").exists() else ""
    return proc.returncode, proc.stdout + proc.stderr, args


class TestProbeScript:
    def test_api_answer_passes(self, tmp_path: pathlib.Path) -> None:
        code, out, _ = _run_script(tmp_path, "400 text/plain; charset=utf-8")

        assert code == 0, out

    @pytest.mark.parametrize(
        "answer",
        [
            "200 text/html",  # the static site: the route is missing
            "404 text/plain; charset=utf-8",  # Gin, but not the handler
            "400 text/html",  # right code, wrong server
            "502 text/html",  # Traefik's error page: api is down
            "000 ",  # nothing answered
        ],
    )
    def test_any_other_answer_fails_and_names_it(self, tmp_path: pathlib.Path, answer: str) -> None:
        code, out, _ = _run_script(tmp_path, answer)

        assert code != 0
        assert answer.strip() in out

    def test_sends_the_request_to_the_real_name_through_the_service(self, tmp_path: pathlib.Path) -> None:
        _, _, args = _run_script(tmp_path, "400 text/plain")
        argv = args.splitlines()

        assert "staging.mlorente.dev:443:traefik.kube-system.svc:443" in argv
        assert "https://staging.mlorente.dev/api/subscribe" in argv
        assert argv[argv.index("-X") + 1] == "POST"
        assert argv[argv.index("--data-raw") + 1] == "{"
