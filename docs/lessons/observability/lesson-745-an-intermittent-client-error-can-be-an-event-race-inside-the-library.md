---
id: lesson-745-an-intermittent-client-error-can-be-an-event-race-inside-the-library
type: lesson
status: active
created: "2026-11-13"
owner: manu
category: observability
tags: [kubelab, observability, uptime-kuma, toolkit]
---

# An intermittent client error can be an event race inside the library

**Context**: `make alerts` asks Uptime Kuma which monitors are DOWN through `uptime-kuma-api` 1.2.1, which keeps a cache filled by socket.io events (#3156).

**Problem**: About one read in four failed with `'list' object has no attribute 'get'`, while Kuma was reachable. Nothing about the network or the server explained it. The library builds each monitor's heartbeats from two events. A live `heartbeat` creates the monitor's list and appends one beat. A `heartbeatList` should then add the history, but if the monitor's list already exists the library calls `append(data)` with the whole list instead of `extend`. Which event comes first depends on timing, so the cache was sometimes `[{beat}, [100 beats]]`. Measured on prod 2026-11-13: monitor 467 had this shape on 2 of 8 reads, and on 5 of 20 later reads.

**Solution**: `kuma_status._flat_beats` spreads a nested history back into beats before picking the newest. The reader no longer assumes the shape the library documents. After the fix, 20 of 20 live reads answered, 5 of them on the nested shape. `tests/test_kuma_down_in_alerts.py` pins the shape with the newest beat on each side of the nesting.

**Rule**: When an error comes and goes against a stable server, reproduce it in a loop and keep the first traceback before blaming the network. Check whether the data's shape differs between good and bad runs. A cache filled by unordered events can produce more than one shape, and the documented one is only the common case.

**Tags**: `#uptime-kuma` `#issue-3458`
