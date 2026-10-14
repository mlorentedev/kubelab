"""#1196: the real-instance tests never point Uptime Kuma at a production target.

`_real_seed()` keeps the seed's field shapes and rewrites where each monitor
connects to the instance itself. A field the rewrite does not know could carry a
new target past it, so every field the seed uses must be declared here as a
target the rewrite covers or as one that is not a target.
"""

from __future__ import annotations

from tests.test_monitoring_integration import SELF_HOST, SELF_URL, _real_seed

TARGETS = {"url", "hostname", "dns_resolve_server"}
NOT_TARGETS = {
    "accepted_statuscodes",
    "active",
    "description",
    "dns_resolve_type",
    "expiryNotification",
    "httpBodyEncoding",
    "ignoreTls",
    "interval",
    "key",
    "keyword",
    "maxredirects",
    "maxretries",
    "method",
    "name",
    "notificationIDList",
    # With the host rewritten, a port only picks a service on the instance itself.
    "port",
    "parent",
    "tags",
    "type",
    "upsideDown",
}


def test_every_seed_field_is_classified() -> None:
    used = {field for monitor in _real_seed() for field in monitor}
    assert used <= TARGETS | NOT_TARGETS, sorted(used - TARGETS - NOT_TARGETS)


def test_every_monitor_checks_the_instance_itself() -> None:
    elsewhere = [
        (monitor["key"], field, monitor[field])
        for monitor in _real_seed()
        for field in sorted(TARGETS)
        if monitor.get(field) and not (monitor["type"] == "dns" and field == "hostname")
        if monitor[field] not in (SELF_HOST, SELF_URL)
    ]
    assert not elsewhere, elsewhere
