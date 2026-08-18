---
id: lesson-057-avahi-blocks-port-5353-on-ubuntu-server
type: lesson
status: active
created: "2026-02-21"
owner: manu
tags: [kubelab, lesson]
---

# Avahi Blocks Port 5353 on Ubuntu Server

**Context**: Deploying CoreDNS on port 5353 on RPi4 (port 53 occupied by Pi-hole).

**Problem**: `avahi-daemon` (mDNS) listens on port 5353 by default on Ubuntu. Docker can't bind the port. Also, disabling just the service isn't enough — the socket (`.socket` unit) restarts it.

**Solution**: `sudo systemctl disable --now avahi-daemon avahi-daemon.socket`. On a headless server, Avahi serves no purpose.

**Rule**: Before assigning an alternative port, check `ss -ulnp | grep <port>`. On headless Ubuntu Server, proactively disable Avahi.
