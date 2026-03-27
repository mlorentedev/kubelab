"""Infrastructure: Node health checks — SSH access, disk, memory, Tailscale, NTP."""

from __future__ import annotations

import pytest

from .fixtures import NodeInfo, node_ssh_run

pytestmark = pytest.mark.infra

_DISK_THRESHOLD = 80  # percent
_MEMORY_THRESHOLD = 80  # percent


class TestNodeHealth:
    """Verify all homelab nodes are healthy via SSH."""

    def test_ssh_access_and_hostname(
        self,
        inventory: list[NodeInfo],
    ) -> None:
        """All nodes must be SSH-accessible and return the expected hostname."""
        errors: list[str] = []
        for node in inventory:
            try:
                result = node_ssh_run(node, "hostname")
                if result.returncode != 0:
                    errors.append(f"{node.name} ({node.host}): SSH failed — {result.stderr.strip()}")
                else:
                    hostname = result.stdout.strip()
                    if node.name not in hostname and hostname not in node.name:
                        errors.append(
                            f"{node.name} ({node.host}): hostname mismatch — got '{hostname}'"
                        )
            except Exception as exc:
                errors.append(f"{node.name} ({node.host}): {exc}")

        assert not errors, "Node SSH/hostname failures:\n" + "\n".join(errors)

    def test_disk_usage_below_threshold(
        self,
        inventory: list[NodeInfo],
    ) -> None:
        """Root filesystem usage must be below threshold on all nodes."""
        errors: list[str] = []
        for node in inventory:
            try:
                result = node_ssh_run(node, "df --output=pcent / | tail -1")
                if result.returncode != 0:
                    errors.append(f"{node.name}: df failed — {result.stderr.strip()}")
                    continue
                usage = int(result.stdout.strip().rstrip("%"))
                if usage >= _DISK_THRESHOLD:
                    errors.append(f"{node.name}: disk at {usage}% (threshold: {_DISK_THRESHOLD}%)")
            except Exception as exc:
                errors.append(f"{node.name}: {exc}")

        assert not errors, "Disk usage alerts:\n" + "\n".join(errors)

    def test_memory_usage_below_threshold(
        self,
        inventory: list[NodeInfo],
    ) -> None:
        """Memory usage must be below threshold on all nodes."""
        errors: list[str] = []
        for node in inventory:
            try:
                result = node_ssh_run(
                    node,
                    "free | awk '/Mem:/ {printf \"%.0f\", $3/$2 * 100}'",
                )
                if result.returncode != 0:
                    errors.append(f"{node.name}: free failed — {result.stderr.strip()}")
                    continue
                usage = int(result.stdout.strip())
                if usage >= _MEMORY_THRESHOLD:
                    errors.append(f"{node.name}: memory at {usage}% (threshold: {_MEMORY_THRESHOLD}%)")
            except Exception as exc:
                errors.append(f"{node.name}: {exc}")

        assert not errors, "Memory usage alerts:\n" + "\n".join(errors)

    def test_tailscale_peers(
        self,
        inventory: list[NodeInfo],
    ) -> None:
        """All nodes must see other Tailscale peers."""
        errors: list[str] = []
        for node in inventory:
            try:
                result = node_ssh_run(node, "tailscale status --peers 2>/dev/null | wc -l")
                if result.returncode != 0:
                    errors.append(f"{node.name}: tailscale status failed — {result.stderr.strip()}")
                    continue
                peers = int(result.stdout.strip())
                if peers < 2:
                    errors.append(f"{node.name}: only {peers} Tailscale peers visible")
            except Exception as exc:
                errors.append(f"{node.name}: {exc}")

        assert not errors, "Tailscale peer failures:\n" + "\n".join(errors)

    def test_ntp_sync(
        self,
        inventory: list[NodeInfo],
    ) -> None:
        """All nodes must have NTP synchronized."""
        errors: list[str] = []
        for node in inventory:
            try:
                result = node_ssh_run(node, "timedatectl show -p NTPSynchronized --value 2>/dev/null || echo unknown")
                if result.returncode != 0:
                    errors.append(f"{node.name}: timedatectl failed — {result.stderr.strip()}")
                    continue
                synced = result.stdout.strip()
                if synced == "unknown":
                    continue  # timedatectl not available on this node
                if synced != "yes":
                    errors.append(f"{node.name}: NTP not synchronized (NTPSynchronized={synced})")
            except Exception as exc:
                errors.append(f"{node.name}: {exc}")

        assert not errors, "NTP sync failures:\n" + "\n".join(errors)
