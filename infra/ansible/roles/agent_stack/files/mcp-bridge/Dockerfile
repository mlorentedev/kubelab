# The MCP bridge (spec AI-009 AC9): mcpo serving the filesystem MCP server over
# the read-only vault mirror. Built on ace2 by the agent_stack role.
#
# mcpo publishes no version tags, only `main`, `latest` and `git-<sha>`. Pinned
# as `main@<digest>`, the digest is what is pulled and Dependabot bumps it when
# `main` moves (same digest as git-788ff92, mcpo 0.0.20).
FROM ghcr.io/open-webui/mcpo:main@sha256:1e82c9555c19e50b80745705f32b47a2647589f35279527b5118ecd3a71bd467

WORKDIR /opt/mcp-bridge
# The filesystem server from the committed lockfile, with no install scripts:
# nothing is resolved at build time that the repository did not pin.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund && npm cache clean --force
COPY config.json launch.py ./

# The image runs as root; the mount is read-only and so is the root filesystem,
# and nobody needs no more.
USER 65534:65534
ENTRYPOINT ["python", "/opt/mcp-bridge/launch.py"]
