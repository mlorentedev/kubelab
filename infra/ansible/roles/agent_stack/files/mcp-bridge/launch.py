"""Start mcpo with its API key, without putting the key on a command line.

mcpo reads the key only from `--api-key`. Given to the container's command, it
would sit in /proc/<pid>/cmdline, which any user on the host can read. Popped
from the environment here, it also never reaches the MCP server mcpo spawns.
"""

import os

from mcpo import app

key = os.environ.pop("MCP_BRIDGE_API_KEY")
port = os.environ["MCP_BRIDGE_PORT"]
app(
    args=[
        "--config",
        "/opt/mcp-bridge/config.json",
        "--host",
        "0.0.0.0",
        "--port",
        port,
        "--api-key",
        key,
        # Without it the OpenAPI spec and the docs answer without the key.
        "--strict-auth",
    ],
    prog_name="mcpo",
)
