---
id: lesson-732-gitea-next-links-name-root-url
type: lesson
status: active
created: "2026-11-11"
owner: manu
category: apps-web
tags: [kubelab, apps-web, forge, gitea, pagination]
---

# Gitea's next-page links name its public ROOT_URL, not the address the client read

**Context**: The API reads Gitea at its in-cluster address and follows the
`Link: rel="next"` header to page through a repository's issues and pull
requests. A same-origin guard refused any next link on another host, so the
reader token never leaves the forge it was issued for.

**Problem**: Gitea writes every link from `ROOT_URL`, its public address,
whatever host the request reached it on. The first prod read after api 1.7.0
failed on every repository with more than one page
(`forge reconcile: gitea:personal/resume: ... next page points off gitea:3000`),
while single-page repositories read normally, so the console showed only part
of the forge as reachable. The fixture-based tests could not catch it: their
fake server wrote links on its own host.

**Solution**: Gitea's paged read sets `Rehost`. The reader takes only the
path and query from the next link and reads them at the configured base URL,
so the token still only reaches the configured host. GitHub keeps the strict
guard, since its links always name the API host it was read at.
`TestGiteaReaderFollowsANextLinkWrittenForItsPublicAddress` serves a link on
another host and fails with the old guard and with a rehost that keeps the
link's host.

**Rule**: A forge behind a proxy or read at an internal address builds its
links from its configured public URL. Follow a server-built link by its path
and query on the host you were given. A fixture that writes links on its own
host does not test pagination.

**Tags**: `#forge` `#gitea` `#console-004`
