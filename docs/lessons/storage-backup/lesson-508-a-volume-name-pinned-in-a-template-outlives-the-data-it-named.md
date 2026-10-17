---
id: lesson-508-a-volume-name-pinned-in-a-template-outlives-the-data-it-named
type: lesson
status: active
created: "2026-10-02"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, uptime-kuma, rpi3, docker, volumes]
---

# A volume name pinned in a template outlives the data it named, and the next provision mounts the orphan

**Context**: rpi3 was provisioned on 2026-10-02 to clear the drift #1983 found (lesson-506 covers the health check that failed first). rpi3 runs Uptime Kuma, the external monitor of prod (ADR-028).

**Problem**: The `rpi3_services` Compose template declared the Kuma volume as `name: uptime-kuma_uptime_kuma_data`, `external: true`. That was lesson-226's fix in March: pin the exact name the ad-hoc container used. Afterwards the data moved to `uptime_kuma_data`, the container was recreated on that volume outside the role, and the old volume froze on 2026-03-28. #1092 recorded both volumes and named `uptime_kuma_data` as live, and `backup.sources.rpi3.uptime_kuma.volume` in `common.yaml` reads that one. The template was never updated. The first provision since then rendered the template, compose saw a different volume, and recreated `uptime-kuma` on the orphan. The external monitor of prod ran on its March state from about 03:03Z to 03:38Z: March monitors, March notification targets, March history. The provision reported success. The live volume was untouched, so nothing was lost, but the heartbeats from that window went into the orphan, and any alert Kuma sent then came from a six-month-old configuration.

**Solution**: The template reads the name from the declaration the backup already uses. `provision-rpi3.yml` passes `uptime_kuma_volume: "{{ config.backup.sources.rpi3.uptime_kuma.volume }}"`, and the template renders `name: {{ uptime_kuma_volume }}`. With that, the backup and the container cannot name different volumes. `tests/test_rpi3_kuma_volume_is_the_backed_up_one.py` fails if the role var stops being that expression, if the template hardcodes a name, or if the declaration names the orphan. The check-mode diff showed `-name: uptime-kuma_uptime_kuma_data` / `+name: uptime_kuma_data`. After the apply, `docker inspect uptime-kuma` read `uptime_kuma_data -> /app/data`, and the container was healthy and answered 302.

**Rule**: A volume name written as a literal in a template is a second declaration of state. It stays correct only until the data moves, and nothing reports the moment it stops. Derive it from the same key the backup reads, so that "what the service mounts" and "what we back up" are one value. Before provisioning a node that holds state after a long gap, dry-run with `--diff` and read every volume and mount line. A `changed` on a container that holds state is a question to answer before the apply, not after.

**Tags**: `#docker` `#ansible` `#uptime-kuma` `#volumes` `#issue-1092` `#issue-1983` `#lesson-226`
