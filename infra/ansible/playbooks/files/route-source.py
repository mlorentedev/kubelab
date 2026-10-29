#!/usr/bin/env python3
"""Say which address this machine sends from to reach a destination, and whether
that address is on the tailnet (#2801).

The edge's LAN address is reachable over the tailnet too, through the subnet route
the edge advertises. A machine that accepts that route looks it up before its own
LAN route, so the address a run targets does not say which path it takes. The
source address the kernel picks for it does. Connecting a UDP socket asks the
kernel for that route and sends nothing.

Usage: route-source.py <destination> <tailnet cidr>
Prints one JSON object: {"source": "<address>", "tailnet": true|false}

The edge play runs it; `make edge-boot-check` loads `route` from it.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import sys


def route(destination: str, tailnet: str) -> dict[str, object]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((destination, 22))
        source = probe.getsockname()[0]
    return {"source": source, "tailnet": ipaddress.ip_address(source) in ipaddress.ip_network(tailnet)}


def main(destination: str, tailnet: str) -> int:
    print(json.dumps(route(destination, tailnet)))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
