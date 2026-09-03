"""SEC-006 (#1557): the VPS's cloud firewall must be attached, and must match the SSOT.

#1538 found port 9000 answering the public internet. Three controls had failed,
and the third is the reason this file exists: `hcloud_firewall.vps` was declared
in infra/terraform/compute/ and attached to the server *in the configuration* --
but that module has never been applied. It read as protection and was not.

The lesson is not "apply the module". It is that **a declaration is not evidence
about a running system**, and no test that only reads the repo can tell the two
apart. A static test would have passed happily throughout the entire window in
which prod had no firewall at all -- it would have confirmed the declaration,
which was never in doubt.

So this file has two layers, and only the second one answers the real question:

- `TestTheDeclarationIsInternallyConsistent` runs in CI. It asserts the SSOT is
  wired to everything that consumes it. It proves the *intent* is coherent. It
  proves nothing about prod, and is written not to pretend otherwise.
- `TestTheFirewallIsLive` asks Hetzner what is actually attached to the running
  server and compares rules. Marked `infra` (needs the API token), the same
  shape as the live half of #1548 -- because "a merged template is not a
  deployed one" was the finding that made #1548 necessary, and it applies here
  with more force: this control is one API call away from being silently gone.
"""

from __future__ import annotations

import os
import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
COMMON_VALUES = REPO_ROOT / "infra/config/values/common.yaml"
MODULE_DIR = REPO_ROOT / "infra/terraform/vps-firewall"
PROVISION_PLAYBOOK = REPO_ROOT / "infra/ansible/playbooks/provision.yml"
DR_MODULE = REPO_ROOT / "infra/terraform/compute/main.tf"

SSOT_KEY = "networking.firewall.vps_inbound"


def _ssot_rules() -> list[dict]:
    data = yaml.safe_load(COMMON_VALUES.read_text(encoding="utf-8")) or {}
    rules = data.get("networking", {}).get("firewall", {}).get("vps_inbound", [])
    assert rules, f"{SSOT_KEY} is missing or empty in common.yaml"
    return rules


def _as_set(rules) -> set[tuple[int, str]]:
    """Normalise either representation to {(port, proto)} so the two can be compared."""
    return {(int(r["port"]), str(r["proto"]).lower()) for r in rules}


class TestTheDeclarationIsInternallyConsistent:
    """CI-able. Proves the SSOT is wired, NOT that prod is protected."""

    def test_ssh_is_present(self) -> None:
        """Without 22/tcp, applying the module locks everyone out of the host.

        Headscale runs on this same VPS, so the VPN is not a way back in -- the
        recovery path and the thing being firewalled are the same machine. Only
        Hetzner's web console remains. Terraform validates this too; the check is
        duplicated here so it fails in CI, before anyone reaches a plan.
        """
        assert (22, "tcp") in _as_set(_ssot_rules()), (
            f"22/tcp is absent from {SSOT_KEY}. Attaching a firewall without it "
            "removes SSH from the production VPS, and Headscale being on the same "
            "host means the tailnet cannot be used to get back in."
        )

    def test_the_ansible_side_reads_the_ssot_rather_than_its_own_copy(self) -> None:
        """The divergence that caused this spec must not be reintroduced.

        Before SEC-006 the list existed twice -- base_system's role default and
        the DR module -- and they disagreed by one port. The fix is not that the
        two copies now match; it is that there is one declaration and the ufw
        side reads it.
        """
        playbook = PROVISION_PLAYBOOK.read_text(encoding="utf-8")
        assert "config.networking.firewall.vps_inbound" in playbook, (
            f"provision.yml no longer reads {SSOT_KEY} for the VPS's ufw rules. "
            "If that wiring is removed, ufw silently falls back to base_system's "
            "fleet default and can drift from the cloud firewall again -- which is "
            "the exact condition SEC-006 was opened to end."
        )

    def test_the_module_does_not_manage_the_server(self) -> None:
        """The design property, asserted rather than trusted to a comment.

        `resource "hcloud_server"` here would put the production VPS into this
        module's state, at which point a configuration mismatch can plan a
        REPLACEMENT of prod. A `data` source cannot. This is the guard that keeps
        a future edit from quietly converting one into the other.
        """
        main_tf = (MODULE_DIR / "main.tf").read_text(encoding="utf-8")
        assert 'resource "hcloud_server"' not in main_tf, (
            "infra/terraform/vps-firewall/ declares a MANAGED hcloud_server. This "
            "module must only ever read the server through a data source: managing "
            "it means a config mismatch in server_type/image/ssh_keys/user_data can "
            "plan a replacement of the production VPS. Attach via "
            "hcloud_firewall_attachment instead."
        )
        assert 'data "hcloud_server"' in main_tf, (
            "The server lookup is gone. Without it there is nothing to attach the "
            "firewall to, and the module would create an orphan firewall that "
            "protects nothing while appearing to."
        )

    def test_no_terraform_description_interpolates_prose(self) -> None:
        """HCL expands `${...}` inside ANY quoted string, a `description` included.

        Measured 2026-09-02: this module's `firewall_name` description explained
        that its value is deliberately distinct from the DR module's
        `${project_name}-vps`. Terraform read that prose as an interpolation and
        refused to *initialise* -- "Variables may not be used here" -- so the
        first `plan` ever attempted against a real account died before a provider
        was downloaded.

        The bug survived 1810 passing tests because nothing in this repo runs
        `terraform validate`, and nothing can: no CI workflow installs Terraform,
        so a test that shelled out to it would skip in CI and assert nothing --
        the vacuity failure this same session filed as #1565. A text check is
        weaker than `validate` but it actually runs, and it covers the whole
        class: interpolation in a description is always prose, never intent.

        The escape is `$${...}`, which renders the literal.
        """
        offenders = []
        pattern = re.compile(r'^\s*description\s*=\s*"([^"]*)"', re.MULTILINE)
        for tf_file in sorted((REPO_ROOT / "infra/terraform").rglob("*.tf")):
            if ".terraform" in tf_file.parts:
                continue
            for match in pattern.finditer(tf_file.read_text(encoding="utf-8")):
                if re.search(r"(?<!\$)\$\{", match.group(1)):
                    rel = tf_file.relative_to(REPO_ROOT)
                    offenders.append(f"{rel}: {match.group(1)[:80]}")

        assert not offenders, (
            "A Terraform `description` contains an unescaped ${...}, which HCL "
            "expands as an interpolation rather than printing. This breaks "
            "`terraform init` for the whole module -- before any provider is "
            "fetched, so the error names the description, not the resource you "
            "were changing. Write $${...} to mean the literal.\n  "
            + "\n  ".join(offenders)
        )

    def test_the_dr_module_is_not_the_one_being_applied(self) -> None:
        """infra/terraform/compute/ stays recreate-only DR (ADR-020, Layer 0).

        It declares a similar firewall. Reading that declaration as evidence that
        prod was protected is what let #1538 run for months. The header saying so
        did not prevent the misreading -- twice, by the same reader -- so the
        property is asserted here as well.
        """
        dr = DR_MODULE.read_text(encoding="utf-8")
        assert "NOT imported against the current VPS" in dr, (
            "infra/terraform/compute/main.tf lost the header declaring it a "
            "recreate-only DR module. That header is load-bearing: ADR-020 makes "
            "this module Layer 0 of disaster recovery, and without the note the "
            "next reader concludes prod's firewall is managed there. It is not."
        )


@pytest.mark.infra
class TestTheFirewallIsLive:
    """Asks Hetzner, not the repo. This is the layer that answers the question.

    Skipped without HCLOUD_TOKEN. That skip is a real gap, not a pass -- see the
    module docstring: nothing in CI can establish that prod is protected.
    """

    @pytest.fixture(scope="class")
    @staticmethod
    def attached_rules() -> set[tuple[int | None, str]]:
        """Read the firewall from Hetzner and return its inbound {(port, proto)}.

        A NOTE ON THE RESPONSE SHAPE. This was written without a token to hand,
        so the field layout below is believed, not confirmed. Every access is
        therefore asserted rather than defaulted: no `.get(x) or .get(y)`
        fallback chain, no `isinstance` hedge. A hedged read of an API whose
        shape you guessed does not fail when the guess is wrong -- it quietly
        selects the branch that happens to parse and certifies the belief. That
        is #1546's FakeClient, which echoed a `permission` value no real Gitea
        returns and kept fourteen tests green over a dead capability.

        So: if the shape is wrong, the first run with a real token fails and
        says which key was missing. That is the intended behaviour, not a bug
        to work around -- correct the accessor, do not add a fallback.
        """
        token = os.environ.get("HCLOUD_TOKEN")
        if not token:
            pytest.skip(
                "HCLOUD_TOKEN not set, so the live check did not run. Nothing else "
                "in this repo can tell an applied firewall from a declared one, so "
                "this skip means prod's firewall is UNVERIFIED -- not that it is "
                "fine. Run `make test-vps-firewall-live`, which injects the token "
                "from SOPS into this process's environment. Do not export it by "
                "hand from `make secrets-show`: that puts a live credential in your "
                "shell history and in any transcript it is pasted into."
            )

        import httpx

        data = yaml.safe_load(COMMON_VALUES.read_text(encoding="utf-8")) or {}
        vps = data.get("networking", {}).get("vps", {})

        # `hostname` is the OS hostname and is NOT what Hetzner calls this
        # machine. Reading it here (as this fixture originally did, defaulted to
        # "kubelab-vps") looks up a server that does not exist and reports the
        # firewall as missing -- a false alarm indistinguishable from the real
        # one this test exists to raise. Asserted, never defaulted.
        server_name = vps.get("hetzner_server_name")
        assert server_name, (
            "networking.vps.hetzner_server_name is absent from common.yaml. It is the "
            "name the HETZNER ACCOUNT uses, which differs from networking.vps.hostname "
            "(the OS hostname). Without it this check cannot find the server, and a "
            "lookup failure would read as an unprotected VPS."
        )
        expected_ip = vps.get("public_ip")
        assert expected_ip, "networking.vps.public_ip is absent; the server cannot be confirmed."

        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(base_url="https://api.hetzner.cloud/v1", headers=headers, timeout=20) as c:
            servers = c.get("/servers", params={"name": server_name}).raise_for_status().json()
            assert servers.get("servers"), (
                f"No Hetzner server named {server_name!r} in this account. Either it was "
                "renamed in the console (update networking.vps.hetzner_server_name) or "
                "this is looking in the wrong project. Do NOT read this as 'the firewall "
                "is fine' -- the check did not run."
            )
            server = servers["servers"][0]

            assert "public_net" in server, (
                "Hetzner's server object has no `public_net` key. The response shape "
                f"assumed by this test is wrong; the keys present are {sorted(server)}. "
                "Fix the accessor to match the real API -- do NOT add a fallback."
            )
            # Confirm the name resolved to the machine this spec is about. A
            # name can be changed or reused; the IP is the identity that matters,
            # and without this the test would happily report on the wrong server.
            resolved_ip = server["public_net"].get("ipv4", {}).get("ip")
            assert resolved_ip == expected_ip, (
                f"Server {server_name!r} resolves to {resolved_ip}, not the expected "
                f"{expected_ip} (networking.vps.public_ip). This is not the production "
                "VPS. Do not adjust the expectation to match -- find out which machine "
                "this is."
            )

            attached = server["public_net"].get("firewalls")
            assert attached is not None, (
                "`public_net` has no `firewalls` key. Shape assumption is wrong; keys "
                f"present are {sorted(server['public_net'])}. Fix the accessor."
            )

            assert attached, (
                f"The production VPS ({server_name}) has NO cloud firewall attached. "
                "This is the exact state SEC-006 was opened to fix (#1557): every port "
                "any process publishes is reachable from the internet, and ufw cannot "
                "cover a published port (#959). Run `make tf-vps-firewall-apply`."
            )

            entry = attached[0]
            assert isinstance(entry, dict) and "id" in entry, (
                f"Expected each entry of public_net.firewalls to be an object with an "
                f"`id`; got {entry!r}. Fix the accessor to match the real API."
            )
            fw = c.get(f"/firewalls/{entry['id']}").raise_for_status().json()["firewall"]

        assert "rules" in fw, (
            f"The firewall object has no `rules` key; keys present are {sorted(fw)}. "
            "Fix the accessor."
        )

        # `and r.get("port")` used to filter here, and it was a hole of exactly
        # the kind this file is about. Hetzner represents icmp/gre/esp rules with
        # a NULL port, so that condition silently dropped them -- an ICMP rule
        # added in the console would never appear in `extra`, and the guard would
        # report a clean match over a firewall that had been edited out of band.
        # The operator's decision was explicitly NO ICMP, so that is precisely
        # the drift this test exists to catch.
        #
        # Portless protocols now normalise to a None port, which the SSOT (tcp/udp
        # only, enforced in variables.tf) can never produce -- so any such rule
        # lands in `extra` and fails loudly instead of being invisible.
        inbound = set()
        for r in fw["rules"]:
            direction = r.get("direction")
            assert direction in ("in", "out"), (
                f"Firewall rule has direction {direction!r}, which this test does not "
                f"understand: {r!r}. It was written for 'in'/'out'. Fix the accessor "
                "rather than letting an unrecognised rule be skipped."
            )
            if direction != "in":
                continue
            port = r.get("port")
            inbound.add((int(port) if port else None, str(r["protocol"]).lower()))
        return inbound

    def test_the_live_rules_match_the_ssot(self, attached_rules: set[tuple[int | None, str]]) -> None:
        """Detached, deleted, or edited out of band -- all three fail here.

        Comparing as sets in both directions matters. A missing rule is an
        outage waiting to happen; an EXTRA rule is an open port nobody declared,
        which is how #1538 looked from the outside.
        """
        declared = _as_set(_ssot_rules())

        missing = declared - attached_rules
        extra = attached_rules - declared

        assert not missing and not extra, (
            "The live Hetzner firewall does not match common.yaml.\n\n"
            f"Declared but NOT live (traffic you expect to work may be dropped): {sorted(missing)}\n"
            f"Live but NOT declared (open ports nobody wrote down): {sorted(extra)}\n\n"
            f"SSOT is {SSOT_KEY}. Reconcile with `make tf-vps-firewall-plan`, read the "
            "plan, then apply. Do NOT edit the firewall in the Hetzner console -- an "
            "out-of-band edit is invisible to every other check in this repo, which is "
            "precisely why this test asks the API instead of reading the config."
        )
