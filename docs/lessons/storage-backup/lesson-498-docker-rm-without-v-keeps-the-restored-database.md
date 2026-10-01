---
id: lesson-498-docker-rm-without-v-keeps-the-restored-database
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, postgres, docker, restore-drill, secrets]
---

# `docker rm` without `-v` keeps the restored database: the image declares the volume

**Context**: BACKUP-046's restore drill (`make backup-drill-postgres`) loads prod's `pg_dumpall` into a throwaway `postgres` container on the workstation, compares counts with live, and removes the container in a `finally`. The emergency restore earlier the same day used the same container shape by hand.

**Problem**: The teardown was `docker rm -f <name>`, and the check that it worked was `docker ps -a --filter name=pgdrill` coming back empty. Both were true and the data was still on disk. The `postgres` image declares `VOLUME /var/lib/postgresql/data`, so `docker run` without a `-v` of its own creates an anonymous volume for the data directory, and `docker rm` keeps a container's volumes unless you pass `-v`. Every run left a complete restored copy of prod, role password hashes included, in a dangling volume that no cleanup touched. Two were on the workstation when the adversarial review found it. The teardown was also guarded by `if started`, so a `docker run -d` that created the container and then failed to start it skipped removal entirely.

**Solution**: `docker rm -f -v <name>`, unconditional in the `finally` (removing an absent name is harmless). A test asserts `-v` on the success path, on a failed start and on a failed load, and each was mutated back to prove it goes red. The two dangling volumes were found by looking for `PG_VERSION` inside every dangling volume, not by their names, and removed. The runbook's manual restore now says to remove the scratch container with `-v` too. The review of that fix found the next gap: the drill ignored the exit code of `docker rm`, so a removal that failed still passed. The exit code cannot settle it either, because `docker rm` is non-zero both when it fails and when the container never existed. So `remove_scratch_container` reads back: it lists the container's volumes before removing it, then requires docker to answer `No such container` and `no such volume` for each one. A drill whose data survives the teardown now fails even if the restore itself was complete.

**Rule**: a container you put sensitive data into is cleaned up only when its volumes are. Check the image for a `VOLUME` declaration (`docker image inspect -f '{{.Config.Volumes}}' <image>`): databases, caches and most stateful images have one. Then verify a teardown by the data, never by the container: `docker volume ls -f dangling=true` before and after, or look inside for the data's own marker. "The container is gone" says nothing about where its data went.

**Tags**: `#docker` `#postgres` `#restore-drill` `#issue-1111`
