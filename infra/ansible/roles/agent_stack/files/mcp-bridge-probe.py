"""Probe the MCP bridge from inside Open WebUI's container (spec AI-009 AC9).

Run with `docker exec -i open-webui python3 -`, the script on stdin. It reads
the bridge's address and key from the connection Open WebUI itself was given,
so the key never appears on a command line or in the play's output, and what
it measures is the path Open WebUI takes. It prints one JSON object.
"""

import json
import os
import urllib.error
import urllib.request

[connection] = json.loads(os.environ["TOOL_SERVER_CONNECTIONS"])
base = connection["url"]


def call(path: str, body: object = None, key: str | None = connection["key"]) -> tuple[int, object]:
    request = urllib.request.Request(base + path, method="POST" if body is not None else "GET")
    request.add_header("Content-Type", "application/json")
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(request, data, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, None


unauthenticated, _ = call("/openapi.json", key=None)
status, spec = call("/openapi.json")
paths = sorted(p.strip("/") for p in (spec or {}).get("paths", {}))
listed, listing = call("/list_directory", {"path": "/vault"})
print(
    json.dumps(
        {
            "unauthenticated": unauthenticated,
            "spec": status,
            "tools": paths,
            "listing": listed,
            "entries": len(str(listing or "").splitlines()),
        }
    )
)
