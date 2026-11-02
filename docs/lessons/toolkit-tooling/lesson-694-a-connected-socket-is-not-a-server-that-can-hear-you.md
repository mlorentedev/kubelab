---
id: lesson-694-a-connected-socket-is-not-a-server-that-can-hear-you
type: lesson
status: active
title: "A connected socket is not a server that can hear you"
created: "2026-11-02"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, testing, uptime-kuma]
---

# A connected socket is not a server that can hear you

**Context**: `tests/test_monitoring_integration.py` hung one `login` for 60 s in about 1 run of 28, and once in CI on #2934. Earlier measurements had ruled out CPU load and the rate limiter and left a lost event as the hypothesis.

**Problem**: Uptime Kuma 2.2.1's `io.on("connection")` handler starts with `await sendInfo(socket, true)` and registers `socket.on("login")` after it. `uptime_kuma_api` returns from its constructor once the socket connects, so a `login` sent right away can arrive during that `await`. Socket.IO drops an event with no listener and sends no ack, and the client waits for its whole timeout. The gap is a settings read, so it widens when the database is busy, as it is after an apply. Twenty-eight loops of the file could not catch it, and reading `server/server.js` from the image did.

**Solution**: `monitoring.GreetedKumaApi` waits for the first `info` event before the constructor returns. The handlers register in the continuation right after that emit, so seeing it proves `login` will be heard. `_connect`, the password rotation and the test client all use it. `TestLoginIsHeard` patches a 500 ms delay into the real server's `sendInfo` call, which turned a 1-in-28 hang into a certain failure: the plain client timed out, and the greeted one logged in within 0.6 s.

**Rule**: When a call hangs rarely with no error, read the server's handler registration before looping the test. An event-driven server can accept a connection before it listens for anything, so wait for a signal the server sends after it is ready, and stretch the gap on purpose to prove the fix.

**Tags**: `#testing` `#socketio` `#issue-1985`
