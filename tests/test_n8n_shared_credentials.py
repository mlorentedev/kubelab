"""APP-CONFIG-018: the sale digest, and the shared SMTP credential it is the first user of.

`make import-n8n` rebuilt one Header Auth credential per workflow. The daily sale
digest is the first workflow that sends email, and other apps will send email
too, so SMTP is not the digest's: `kubelab-smtp` is declared once in
`N8N_SHARED_CREDENTIALS`, rendered from the `infra.smtp.*` the API and Authelia
already read (ADR-036), and upserted once per run however many workflows
reference it.

What these tests pin is what n8n and the operator will observe, run against a
fake `kubectl` that records every payload piped into the pod:

- which credentials and workflows a prod run imports, and in what order;
- that a missing value fails that workflow closed, names the SOPS path and prints
  no value (the vault here holds sentinels, so a leak is greppable);
- that removing the sale on 2026-11-09 leaves `kubelab-smtp` in place.

The vault is the SHIPPED plaintext config plus sentinel secrets: the pins on
`infra.smtp.host`/`port` read the real SSOT, the way the dry-run test in
`test_n8n_import.py` reads it, rather than answering for a key nobody wrote.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from toolkit.features import n8n_import
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.n8n_import import (
    N8N_IMPORT_CATALOG,
    N8N_SHARED_CREDENTIALS,
    PLACEHOLDER_SSOT,
    N8nImportSpec,
    import_n8n_workflow,
    read_credential_refs,
    read_workflow_ids,
    render_smtp_credential,
)
from toolkit.features.secrets_manager import SECRET_CATALOG

REPO_ROOT = Path(__file__).resolve().parent.parent
SALE_JSON = "infra/n8n/workflows/sale-metrics-daily-digest.json"
SALE_PATHS = {
    "token": "apps.services.automation.n8n.sale_digest.analytics_token",
    "recipient": "apps.services.automation.n8n.sale_digest.recipient",
    "site_tag": "apps.services.automation.n8n.sale_digest.site_tag",
}
SMTP_PATHS = {
    "host": "infra.smtp.host",
    "port": "infra.smtp.port",
    "user": "infra.smtp.user",
    "pass": "infra.smtp.pass",
}

# Sentinels: distinctive enough that a leak into the output is a plain substring hit.
TOKEN = "CF-TOKEN-SENTINEL-4417"
RECIPIENT = "recipient-sentinel@example.test"
SITE_TAG = "SITETAG-SENTINEL-9051"
SMTP_PASS = "SMTP-PASS-SENTINEL-2263"
SMTP_USER = "relay-sentinel@example.test"
NOTIFY_HEADER = "NOTIFY-HEADER-SENTINEL-7730"
SENTINELS = (TOKEN, RECIPIENT, SITE_TAG, SMTP_PASS, SMTP_USER, NOTIFY_HEADER)


# ── Fakes ─────────────────────────────────────────────────────────────────────


def _vault() -> dict[str, Any]:
    """Shipped prod plaintext config, with sentinel secrets laid over it."""
    config = ConfigurationManager(env="prod").get_plaintext_values()
    secrets: dict[str, Any] = {
        "infra": {"smtp": {"user": SMTP_USER, "pass": SMTP_PASS}},
        "apps": {
            "services": {
                "automation": {
                    "notify": {"webhook_secret": NOTIFY_HEADER},
                    "n8n": {
                        "sale_digest": {"analytics_token": TOKEN, "recipient": RECIPIENT, "site_tag": SITE_TAG},
                    },
                }
            }
        },
    }
    return _deep_update(config, secrets)


def _deep_update(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _deep_update(dst[key], value)
        else:
            dst[key] = value
    return dst


def _without(vault: dict[str, Any], path: str) -> dict[str, Any]:
    out = copy.deepcopy(vault)
    node = out
    *parents, leaf = path.split(".")
    for part in parents:
        node = node[part]
    del node[leaf]
    return out


class _Cm:
    """Stands in for ConfigurationManager over a dict, with the two reads the importer makes."""

    def __init__(self, vault: dict[str, Any]) -> None:
        self.vault = vault

    def get_merged_config(self) -> dict[str, Any]:
        return self.vault

    def get_secret_by_path(self, path: str) -> str | None:
        node: Any = self.vault
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return None if node is None or isinstance(node, (dict, list)) else str(node)


class _Kubectl:
    """Records every exec'd import: its kind, and the JSON piped on stdin."""

    def __init__(self, fail_kind: str | None = None, echo: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.imports: list[tuple[str, Any]] = []
        self.fail_kind = fail_kind
        # The real fake returns empty stdout, so it cannot see a CLI that repeats
        # its input. `echo` makes every exec answer with the payload it was fed.
        self.echo = echo

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        if cmd[1:3] == ["get", "pods"]:
            pod = {
                "metadata": {"name": "n8n-live"},
                "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
            }
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"items": [pod]}), stderr="")
        if cmd[1] == "exec" and "sh" in cmd:
            script = cmd[-1]
            kind = "credentials" if "import:credentials" in script else "workflow"
            fed = kwargs["input"] if self.echo else ""
            if kind == self.fail_kind:
                raise subprocess.CalledProcessError(1, cmd, stderr=f"import failed: {fed}")
            self.imports.append((kind, json.loads(kwargs["input"])))
            return subprocess.CompletedProcess(cmd, 0, stdout=fed, stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def credentials(self) -> list[dict[str, Any]]:
        return [c for kind, payload in self.imports if kind == "credentials" for c in payload]

    def workflows(self) -> list[dict[str, Any]]:
        return [payload for kind, payload in self.imports if kind == "workflow"]

    def order(self) -> list[str]:
        """`credential:<name>` / `workflow:<name>` in the order they landed."""
        out = []
        for kind, payload in self.imports:
            out += (
                [f"credential:{c['name']}" for c in payload]
                if kind == "credentials"
                else [f"workflow:{payload['name']}"]
            )
        return out


def _run(
    env: str = "prod",
    *,
    vault: dict[str, Any] | None = None,
    kubectl: _Kubectl | None = None,
    catalog: list[N8nImportSpec] | None = None,
    root: Path = REPO_ROOT,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[bool, _Kubectl]:
    kubectl = kubectl or _Kubectl()
    cm = _Cm(vault if vault is not None else _vault())
    monkeypatch.setattr(n8n_import, "ConfigurationManager", lambda *a, **k: cm)
    monkeypatch.setattr(n8n_import.subprocess, "run", kubectl)
    if catalog is not None:
        monkeypatch.setattr(n8n_import, "N8N_IMPORT_CATALOG", catalog)
    return import_n8n_workflow(env, root), kubectl


def _sale_spec() -> N8nImportSpec:
    return next(s for s in N8N_IMPORT_CATALOG if str(s.workflow_path) == SALE_JSON)


def _smtp() -> Any:
    return next(c for c in N8N_SHARED_CREDENTIALS if c.name == "kubelab-smtp")


def _sale_doc() -> dict[str, Any]:
    return json.loads((REPO_ROOT / SALE_JSON).read_text())


def _mailer(tmp_path: Path, name: str, workflow_id: str, ref: dict[str, str] | None = None) -> N8nImportSpec:
    """A minimal workflow with one email node, and the catalog entry for it."""
    ref = ref or {"id": _smtp().credential_id, "name": "kubelab-smtp"}
    doc = {
        "id": workflow_id,
        "name": name,
        "nodes": [{"name": "Mail", "type": "n8n-nodes-base.emailSend", "credentials": {"smtp": ref}}],
        "connections": {},
    }
    (tmp_path / f"{name}.json").write_text(json.dumps(doc))
    return N8nImportSpec(workflow_path=Path(f"{name}.json"), envs=frozenset({"prod"}))


# ── The shared credential: shape ──────────────────────────────────────────────


class TestSmtpCredentialShape:
    def test_it_is_the_smtp_credential_n8n_reads(self) -> None:
        """Field names from n8n 2.12.3 `Smtp.credentials.ts` (the pinned image): a
        renamed field is not an error in n8n, the node just connects with the
        default, which is port 465 over implicit TLS."""
        entry = json.loads(render_smtp_credential("cid", "kubelab-smtp", "smtp.example.test", 587, "u", "p"))[0]
        assert entry["type"] == "smtp"
        assert (entry["id"], entry["name"]) == ("cid", "kubelab-smtp")
        assert set(entry["data"]) == {"user", "password", "host", "port", "secure", "disableStartTls"}
        assert entry["data"] == {
            "user": "u",
            "password": "p",
            "host": "smtp.example.test",
            "port": 587,
            "secure": False,
            "disableStartTls": False,
        }

    @pytest.mark.parametrize(("port", "secure"), [(465, True), (587, False), (25, False)])
    def test_secure_means_implicit_tls_so_it_follows_the_port(self, port: int, secure: bool) -> None:
        """n8n's `secure` is nodemailer's: true is implicit TLS (465); STARTTLS on
        587 needs false. Copied verbatim, `infra.smtp.secure: true` ("require TLS"
        to the API and Authelia) on port 587 fails the first connection."""
        entry = json.loads(render_smtp_credential("cid", "n", "h", port, "u", "p"))[0]
        assert entry["data"]["secure"] is secure

    def test_the_imported_payload_is_built_from_infra_smtp_not_a_second_copy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vault = _vault()
        vault["infra"]["smtp"].update(host="relay.example.test", port=465, secure=False)
        ok, kubectl = _run(vault=vault, monkeypatch=monkeypatch)
        assert ok
        smtp = next(c for c in kubectl.credentials() if c["name"] == "kubelab-smtp")
        assert smtp["data"] | {"password": "-"} == {
            "user": SMTP_USER,
            "password": "-",
            "host": "relay.example.test",
            "port": 465,
            "secure": True,
            "disableStartTls": False,
        }
        assert smtp["data"]["password"] == SMTP_PASS


# ── The workflow ──────────────────────────────────────────────────────────────


class TestSaleDigestWorkflow:
    def test_it_is_a_prod_only_catalog_entry(self) -> None:
        assert _sale_spec().envs == frozenset({"prod"})

    def test_it_reads_nothing_from_env(self) -> None:
        """n8n 2 blocks `$env` in nodes, and a value read from env at start goes
        stale silently. The workflow takes its values from placeholders filled at
        import, which is the only way they reach a node here."""
        assert "$env" not in (REPO_ROOT / SALE_JSON).read_text()

    def test_its_four_header_auth_nodes_share_one_credential_id(self) -> None:
        """Two Analytics Engine queries, the Web Analytics query and its second try."""
        refs = [r for r in read_credential_refs(_sale_doc()) if r.type == "httpHeaderAuth"]
        assert len(refs) == 4
        assert len({r.id for r in refs}) == 1
        assert {r.name for r in refs} == {_sale_spec().credential_name}

    def test_it_references_the_shared_smtp_credential_by_the_registry_id(self) -> None:
        refs = [r for r in read_credential_refs(_sale_doc()) if r.type == "smtp"]
        assert [(r.id, r.name) for r in refs] == [(_smtp().credential_id, "kubelab-smtp")]

    def test_every_placeholder_it_carries_is_mapped_to_a_path_with_an_owner(self) -> None:
        """A mapped path must be shipped config OR a registered secret. Otherwise it
        is a value nothing declares, the shape of every 'absent in production'."""
        tokens = set(re.findall(r"RESOLVE_[A-Z0-9_]+", (REPO_ROOT / SALE_JSON).read_text()))
        assert tokens, "the digest carries no placeholder: its values are hardcoded or read from env"
        assert tokens <= set(PLACEHOLDER_SSOT)
        plaintext = ConfigurationManager(env="prod").get_plaintext_values()
        registered = {s.key_path for s in SECRET_CATALOG}
        for token in tokens:
            path = PLACEHOLDER_SSOT[token]
            assert path in registered or _has(plaintext, path), f"{token} -> {path}: nothing declares it"

    def test_the_sender_is_the_relay_account_the_recipient_a_sale_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Gmail rewrites any From that is not the authenticated account, so the
        sender is `infra.smtp.user`. The recipient and site tag are the sale's own."""
        ok, kubectl = _run(monkeypatch=monkeypatch)
        assert ok
        digest = next(w for w in kubectl.workflows() if w["name"] == _sale_doc()["name"])
        mail = next(n for n in digest["nodes"] if n["type"] == "n8n-nodes-base.emailSend")
        assert mail["parameters"]["fromEmail"] == SMTP_USER
        assert mail["parameters"]["toEmail"] == RECIPIENT
        query = next(n for n in digest["nodes"] if n["name"] == "Web Analytics query")
        assert SITE_TAG in query["parameters"]["jsCode"]
        assert "RESOLVE_" not in json.dumps(digest)


def _has(config: dict[str, Any], path: str) -> bool:
    node: Any = config
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


# ── The run ───────────────────────────────────────────────────────────────────


class TestProdRun:
    def test_credentials_land_before_the_workflow_that_uses_them(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ok, kubectl = _run(monkeypatch=monkeypatch)
        assert ok
        order = kubectl.order()
        digest = f"workflow:{_sale_doc()['name']}"
        for needed in ("credential:kubelab-smtp", f"credential:{_sale_spec().credential_name}"):
            assert order.count(needed) == 1, order
            assert order.index(needed) < order.index(digest), order

    def test_the_cloudflare_credential_is_a_bearer_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, kubectl = _run(monkeypatch=monkeypatch)
        cred = next(c for c in kubectl.credentials() if c["name"] == "cloudflare-analytics-read")
        assert cred["type"] == "httpHeaderAuth"
        assert cred["data"] == {"name": "Authorization", "value": f"Bearer {TOKEN}"}
        assert cred["id"] == read_workflow_ids(_sale_doc())[1]

    def test_staging_imports_neither_the_digest_nor_smtp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ok, kubectl = _run("staging", monkeypatch=monkeypatch)
        assert ok
        assert not [o for o in kubectl.order() if "smtp" in o or "cloudflare" in o]
        assert _sale_doc()["name"] not in " ".join(kubectl.order())

    def test_the_secrets_travel_on_stdin_never_argv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, kubectl = _run(monkeypatch=monkeypatch)
        argv = " ".join(" ".join(c) for c in kubectl.calls)
        for sentinel in SENTINELS:
            assert sentinel not in argv

    def test_nothing_secret_reaches_the_output(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The resolver used to log every value it substituted; the recipient and
        the site tag are SOPS-resident, so that put them on the terminal."""
        ok, _ = _run(monkeypatch=monkeypatch)
        assert ok
        out = capsys.readouterr().out
        for sentinel in SENTINELS:
            assert sentinel not in out
        assert "RESOLVE_SALE_DIGEST_TO" in out, "the log should still name what it resolved"

    @pytest.mark.parametrize("fail_kind", [None, "credentials", "workflow"], ids=["success", "fails-cred", "fails-wf"])
    def test_a_cli_that_repeats_its_input_does_not_put_a_secret_on_the_terminal(
        self, fail_kind: str | None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The payload travels on stdin, and the importer logs what the pod prints:
        stdout on success, stderr on failure. A CLI that echoes its input would carry
        every secret in the payload to the terminal through either one."""
        _run(kubectl=_Kubectl(fail_kind=fail_kind, echo=True), monkeypatch=monkeypatch)
        out = capsys.readouterr().out
        for sentinel in SENTINELS:
            assert sentinel not in out


class TestFailsClosed:
    @pytest.mark.parametrize("name", ["token", "recipient", "site_tag"])
    def test_a_missing_sale_value_fails_the_digest_naming_the_path(
        self, name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = SALE_PATHS[name]
        ok, kubectl = _run(vault=_without(_vault(), path), monkeypatch=monkeypatch)
        assert ok is False
        assert path in " ".join(capsys.readouterr().out.split())
        assert _sale_doc()["name"] not in " ".join(kubectl.order()), "the digest must not import half-configured"

    def test_the_other_workflows_still_import_when_the_digest_cannot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ok, kubectl = _run(vault=_without(_vault(), SALE_PATHS["token"]), monkeypatch=monkeypatch)
        assert ok is False
        landed = [w["name"] for w in kubectl.workflows()]
        assert len(landed) == len([s for s in N8N_IMPORT_CATALOG if "prod" in s.envs]) - 1

    @pytest.mark.parametrize("name", ["host", "port", "user", "pass"])
    def test_a_missing_smtp_value_fails_naming_the_path_and_no_workflow_uses_the_credential(
        self, name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        vault = _without(_vault(), SMTP_PATHS[name])
        ok, kubectl = _run(vault=vault, monkeypatch=monkeypatch)
        assert ok is False
        assert SMTP_PATHS[name] in " ".join(capsys.readouterr().out.split())
        assert "credential:kubelab-smtp" not in kubectl.order()
        assert _sale_doc()["name"] not in " ".join(kubectl.order()), (
            "a workflow must not land pointing at a credential n8n lacks"
        )

    def test_a_failed_shared_import_holds_back_only_the_workflows_that_need_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _FailsSmtp(_Kubectl):
            def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
                if cmd[1] == "exec" and '"type": "smtp"' in (kwargs.get("input") or ""):
                    raise subprocess.CalledProcessError(1, cmd, stderr="import failed")
                return super().__call__(cmd, **kwargs)

        ok, kubectl = _run(kubectl=_FailsSmtp(), monkeypatch=monkeypatch)
        assert ok is False
        landed = [w["name"] for w in kubectl.workflows()]
        assert _sale_doc()["name"] not in landed
        assert len(landed) == len([s for s in N8N_IMPORT_CATALOG if "prod" in s.envs]) - 1

    def test_a_credential_nothing_imports_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A workflow whose node names a credential the run does not create would
        import cleanly and fail at its first execution."""
        spec = _mailer(
            tmp_path, "stray", "d9000000-0000-4000-8000-0000000000aa", {"id": "c-x", "name": "someone-elses-smtp"}
        )
        ok, kubectl = _run(catalog=[spec], root=tmp_path, monkeypatch=monkeypatch)
        assert ok is False
        assert "someone-elses-smtp" in capsys.readouterr().out
        assert kubectl.workflows() == []

    def test_a_shared_credential_referenced_under_the_wrong_id_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = _mailer(
            tmp_path, "wrongid", "d9000000-0000-4000-8000-0000000000bb", {"id": "not-the-id", "name": "kubelab-smtp"}
        )
        ok, kubectl = _run(catalog=[spec], root=tmp_path, monkeypatch=monkeypatch)
        assert ok is False
        assert kubectl.workflows() == []

    def test_header_auth_nodes_that_disagree_on_the_id_are_refused(self) -> None:
        doc = {
            "id": "w",
            "nodes": [
                {"credentials": {"httpHeaderAuth": {"id": "a", "name": "x"}}},
                {"credentials": {"httpHeaderAuth": {"id": "b", "name": "x"}}},
            ],
        }
        with pytest.raises(ValueError, match="disagree"):
            read_workflow_ids(doc)


# ── Shared: one upsert per run; removing the sale leaves it alone ──────────────


class TestSharedLifecycle:
    def test_two_workflows_using_it_import_it_once(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        specs = [
            _mailer(tmp_path, "first", "d9000000-0000-4000-8000-000000000001"),
            _mailer(tmp_path, "second", "d9000000-0000-4000-8000-000000000002"),
        ]
        ok, kubectl = _run(catalog=specs, root=tmp_path, monkeypatch=monkeypatch)
        assert ok
        assert kubectl.order().count("credential:kubelab-smtp") == 1
        assert sorted(w["name"] for w in kubectl.workflows()) == ["first", "second"]

    def test_a_workflow_needs_no_header_auth_credential_to_send_email(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A future mailer is a catalog entry with a workflow path and nothing else."""
        ok, kubectl = _run(
            catalog=[_mailer(tmp_path, "mailer", "d9000000-0000-4000-8000-000000000003")],
            root=tmp_path,
            monkeypatch=monkeypatch,
        )
        assert ok
        assert [c["name"] for c in kubectl.credentials()] == ["kubelab-smtp"]

    def test_removing_the_sale_leaves_the_shared_credential_in_place(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """2026-11-09: delete the sale's catalog entry and its JSON. What stays must
        keep working, and nothing of the sale may be asked of the vault."""
        without_sale = [s for s in N8N_IMPORT_CATALOG if str(s.workflow_path) != SALE_JSON]
        assert len(without_sale) == len(N8N_IMPORT_CATALOG) - 1
        vault = _vault()
        for path in SALE_PATHS.values():
            vault = _without(vault, path)
        ok, kubectl = _run(vault=vault, catalog=without_sale, monkeypatch=monkeypatch)
        assert ok, "the sale's SOPS block is gone too, and the run must not need it"
        assert "credential:kubelab-smtp" in kubectl.order(), "the shared credential must survive the sale"
        assert _smtp() in N8N_SHARED_CREDENTIALS
        assert not [o for o in kubectl.order() if "cloudflare" in o or _sale_doc()["name"] in o]

    def test_no_shared_credential_is_named_for_a_product(self) -> None:
        for cred in N8N_SHARED_CREDENTIALS:
            assert "sale" not in cred.name and "denver" not in cred.name

    def test_the_sale_owns_every_sale_value_and_the_shared_credential_owns_none_of_them(self) -> None:
        """What the 2026-11-09 removal deletes is one block: the three paths below,
        and nothing the shared credential reads."""
        smtp_reads = set(SMTP_PATHS.values())
        assert smtp_reads.isdisjoint(SALE_PATHS.values())
        assert all(p.startswith("apps.services.automation.n8n.sale_digest.") for p in SALE_PATHS.values())


class TestRegistries:
    def test_each_sale_secret_is_registered_for_prod_only(self) -> None:
        by_key = {s.key_path: s for s in SECRET_CATALOG}
        for path in SALE_PATHS.values():
            assert path in by_key, f"{path} has no SECRET_CATALOG entry: `secrets audit` cannot see it"
            assert by_key[path].envs == ("prod",)

    def test_the_cloudflare_token_declares_that_a_provider_expires_it(self) -> None:
        from toolkit.features.secret_expiry import Expiry

        spec = next(s for s in SECRET_CATALOG if s.key_path == SALE_PATHS["token"])
        assert spec.expiry is Expiry.PROVIDER

    def test_the_shared_credentials_target_the_deployment_the_specs_do(self) -> None:
        for cred in N8N_SHARED_CREDENTIALS:
            for spec in N8N_IMPORT_CATALOG:
                assert (cred.namespace, cred.deployment, cred.pod_selector) == (
                    spec.namespace,
                    spec.deployment,
                    spec.pod_selector,
                )

    def test_importing_the_module_reads_no_config(self) -> None:
        """Both registries are module constants. A fresh interpreter, so no earlier test has
        already imported the module; building a `ConfigurationManager` at import (a registry
        derived from SSOT, say) would make `--help` decrypt SOPS (TOOL-097)."""
        script = textwrap.dedent(
            """
            import toolkit.features.configuration as c

            def refuse(*a, **k):
                raise AssertionError("ConfigurationManager built at import")

            c.ConfigurationManager.__init__ = refuse
            import toolkit.features.n8n_import as m
            assert m.N8N_SHARED_CREDENTIALS and m.N8N_IMPORT_CATALOG
            print("imported")
            """
        )
        done = subprocess.run(
            [sys.executable, "-c", script], cwd=REPO_ROOT, capture_output=True, text=True, timeout=120
        )
        assert done.returncode == 0 and "imported" in done.stdout, done.stderr[-2000:]


class TestReadme:
    README = (REPO_ROOT / "infra/n8n/workflows/README.md").read_text()

    def test_it_says_how_a_workflow_sends_email(self) -> None:
        for needed in ("kubelab-smtp", "infra.smtp.user", "RESOLVE_KUBELAB_SMTP_FROM"):
            assert needed in self.README, f"the README must name {needed}"

    def test_it_says_how_to_remove_the_sale_and_what_not_to_remove(self) -> None:
        for needed in (SALE_JSON.rsplit("/", 1)[1], "apps.services.automation.n8n.sale_digest", "2026-11-09"):
            assert needed in self.README, f"the removal steps must name {needed}"
        assert re.search(r"kubelab-smtp[^\n]*(stays|keep|leave)", self.README, re.I | re.S)

    def test_it_names_every_sale_secret_path(self) -> None:
        for path in SALE_PATHS.values():
            assert path in self.README
