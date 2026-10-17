---
id: lesson-467-an-n8n-v2-if-node-with-v1-parameters-always-passes
type: lesson
status: active
created: "2026-09-25"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, n8n, webhooks, security, testing]
---

# An n8n IF node at `typeVersion: 2` with v1-shaped conditions always passes, and `rawBody` never reaches `$json`

**Context**: #1712. `multi-forge-sync` completed without creating a Vikunja
task, and an unsigned staging probe got past its signature gate. The graph
said neither was possible.

**Problem**: Two defects, each hiding the other. Both were measured on
n8n 2.12.3, first by executing n8n's own modules in the pinned image and then
with a probe workflow on a local instance.

1. An IF node at `typeVersion: 2` whose parameters use the v1 shape
   (`conditions.boolean[{value1, value2}]`) is **unconditionally TRUE**. In v2,
   `conditions` is a filter parameter, and `extractValueFilter` begins with
   `if (!isFilterValue(value)) return value;`. The legacy object is not a filter
   value, so the IF receives the object itself as `pass`, and an object is
   truthy. The probe ran a v2 IF with `value1: false` and it took the TRUE
   branch. Four gates in three workflows had this shape, two of them webhook
   signature checks on public routes.
2. Webhook v2 with `options.rawBody: true` puts the raw bytes in
   **`binary.data.data`** (base64). They never reach `$json.rawBody`, which is
   `undefined`. A Code node that falls back to `JSON.stringify($json.body)`
   HMACs a re-serialisation, so a signature from a sender that pretty-prints
   (Gitea does) never validates.

The tests passed throughout because they fed the Code node a `$json.rawBody`
string, a shape n8n never produces. The two defects also masked each other:
the broken gate let unsigned traffic through, so nobody saw that signed
traffic was being rejected.

**Solution**: Read the body with
`await this.helpers.getBinaryDataBuffer(0, 'data')` and HMAC that `Buffer`
directly, not a UTF-8 re-encode of it. `Buffer.from(base64)` works only while
binary data is stored inline. Give every IF, Switch and Filter node at v2+ the
filter shape (`conditions.conditions[]` plus `combinator`), or pin it to v1.
The fix lands under APP-CONFIG-015.

**Rule**: A test that fakes the platform's item shape proves only the fake.
Derive the input shape from the platform (its node source, or a recorded
execution), and guard node-parameter shape against `typeVersion` statically.
Nothing in n8n rejects a mismatched shape: the workflow imports, activates and
answers 200.

**Tags**: `#n8n` `#webhooks` `#hmac` `#issue-1712`
