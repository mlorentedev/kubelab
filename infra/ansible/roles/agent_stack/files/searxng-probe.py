"""Probe SearXNG from inside Open WebUI's container (#2970).

Run with `docker exec -i open-webui python3 -`, the script on stdin. It asks the
URL Open WebUI itself was given (SEARXNG_QUERY_URL), in the format Open WebUI
asks for, so what it measures is the path a chat's web search takes. SearXNG
publishes no port, so this is the only place it can be measured from. It prints
one JSON object.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

url = os.environ["SEARXNG_QUERY_URL"] + "?" + urllib.parse.urlencode({"q": "kubernetes", "format": "json"})
try:
    with urllib.request.urlopen(url, timeout=20) as response:
        status, results = response.status, len(json.load(response).get("results", []))
except urllib.error.HTTPError as error:
    status, results = error.code, 0
except (urllib.error.URLError, OSError, ValueError):
    status, results = 0, 0

print(json.dumps({"status": status, "results": results}))
