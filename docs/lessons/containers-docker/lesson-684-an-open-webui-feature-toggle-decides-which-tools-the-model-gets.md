---
id: lesson-684-an-open-webui-feature-toggle-decides-which-tools-the-model-gets
type: lesson
status: active
created: "2026-11-01"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, open-webui, nan, image-generation]
---

# An Open WebUI feature toggle decides which tools the model gets

**Context**: After the v0.12.5 upgrade (#2885), the operator asked a chat model on
`chat.kubelab.live` for a picture. Image generation was configured and enabled
(`ENABLE_IMAGE_GENERATION=true`, NaN as the engine).

**Problem**: The model answered that it had no image generator, then drew an SVG
by hand and created a workspace skill to store it. Enabling a feature globally
only makes its toggle available. In v0.12.5 the model is offered the builtin
`generate_image` tool only when the chat's `image_generation` feature is on
(`backend/open_webui/utils/tools.py:811-817`). The toggle starts off, so the
model never saw the tool and improvised with the ones it had, including one that
writes to the workspace.

**Solution**: `DEFAULT_MODEL_METADATA='{"defaultFeatureIds": ["image_generation"]}'`
in `webui.env.j2`. The server merges it into every model's metadata where the key
is missing (`utils/models.py:371`), and the chat turns on each default feature
that is available (`Chat.svelte:1116`). With native function calling, the default
here, the toggle only offers the tool. The legacy mode is the one that would
generate an image on every message (`utils/middleware.py:2405`), so the test
also refuses a `function_calling` override in `DEFAULT_MODEL_PARAMS`.

**Rule**: In an agent UI, "enabled" and "offered to the model" are separate
switches. Test a capability by asking the model to use it, and read which tool it
called; an answer can look complete when the model routed around the missing
tool.

**Tags**: `#open-webui` `#image-generation` `#function-calling`
