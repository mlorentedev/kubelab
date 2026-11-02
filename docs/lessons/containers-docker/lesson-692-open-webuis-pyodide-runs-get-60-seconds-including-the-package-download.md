---
id: lesson-692-open-webuis-pyodide-runs-get-60-seconds-including-the-package-download
type: lesson
status: active
created: "2026-11-01"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, open-webui, pyodide, ai-025]
---

# Open WebUI's Pyodide runs get 60 seconds, including the package download

**Context**: AI-025 (#2915) turned on Open WebUI's code interpreter with the
Pyodide engine, so model-written code runs in the operator's browser and never
on ace2. The operator's first test asked for the first 20 primes and a chart.

**Problem**: The primes came back correct, but the first `import matplotlib`
ended in `Execution Time Limit Exceeded`. The limit is a hardcoded 60 s
`setTimeout` in the browser (`src/routes/+layout.svelte`, v0.12.5). No env var
or admin setting changes it, and the clock includes loading the packages.
matplotlib and numpy ship in the image (`scripts/prepare-pyodide.js`), so the
browser downloads them from ace2 over the tailnet on first import. Over a slow
uplink that download alone can exceed 60 s. On timeout Open WebUI terminates the
worker and creates a new one, so a retry starts the download from scratch.
plotly is not bundled at all.

**Solution**: No configuration fixes it. The model recovered by drawing the
chart as SVG with the standard library. A run whose packages are already loaded
in the same tab is not affected.

**Rule**: For browser-side code execution, the time limit covers fetching the
runtime's packages as well as running the code. Judge a timeout by the link the
browser is on, not by how fast the code runs.

**Tags**: `#open-webui` `#pyodide` `#ai-025`
