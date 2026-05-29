---
id: "kubelab-troubleshooting-networking-dns"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Networking & DNS Issues

Problems related to DNS resolution, Traefik routing, inter-container networking, and timeouts in KubeLab.

---

## RPi OS Lite — WiFi not connecting {#rpi-os-lite-wifi}

**Date**: 2026-02-18 | **Device**: kubelab-rpi3

### Symptoms

- `hostname -I` returns nothing (no IP assigned)
- `wlan0` interface is DOWN
- `nmcli dev wifi list` shows no networks (empty output)
- `wpa_supplicant.conf` written manually to boot partition has no effect

### Root Causes (in order of likelihood)

**1. WiFi country not set (most common)**

RPi OS Lite disables the WiFi radio until a country code is configured. Without it, `wlan0` is UP but scans return no results.

```bash
# Fix:
sudo raspi-config nonint do_wifi_country ES
sudo reboot
```

**2. Raspberry Pi Imager customisation not applied**

Imager asks "Would you like to apply OS customisation settings?" after writing. If you click "No" (the default), the image is written without your config (no `firstrun.sh` on boot partition, hostname stays `raspberry`).

```bash
# Verify after flashing (SD still in PC):
ls /media/$USER/bootfs/firstrun.sh
# If missing → config was NOT applied → reflash and click "Yes"
```

**3. Direct ethernet connection (no DHCP) for SSH recovery**

If WiFi is broken and you need to SSH in via cable (laptop ↔ RPi directly, no router), there's no DHCP server — both sides need manual IPs:

```bash
# On RPi (via monitor/keyboard):
sudo ip addr add 192.168.99.2/24 dev eth0
sudo ip link set eth0 up

# On laptop:
sudo ip addr add 192.168.99.1/24 dev <laptop-eth-interface>
# Then: ssh manu@192.168.99.2
```

Note: these IPs are lost on reboot — temporary debug only.

**4. SSH host key conflict after reinstall**

If you've connected to the same IP before, SSH will refuse:

```bash
ssh-keygen -f ~/.ssh/known_hosts -R '10.0.0.157'
```

### Working Setup (verified)

```bash
# After fresh flash + reboot:
sudo raspi-config nonint do_wifi_country ES
sudo reboot

# On reboot:
sudo nmcli dev wifi rescan && sleep 3
sudo nmcli dev wifi list                          # should show networks
sudo nmcli dev wifi connect "SSID" password "PW"
sudo nmcli connection modify "SSID" connection.autoconnect yes
echo "127.0.1.1 kubelab-rpi3" | sudo tee -a /etc/hosts
```

NetworkManager persists the connection across reboots automatically once connected with `nmcli`.

## RPi 4 NAT broken after reboot — K3s nodes lose internet {#rpi4-nat-broken}

**Date**: 2026-02-22 (recurrence of 2026-02-21 HW-019) | **Device**: kubelab-rpi4

### Symptoms

- K3s pods stuck in `ErrImagePull` / `ImagePullBackOff`
- K3s CoreDNS logs: `read udp 10.42.0.x:XXXXX->1.1.1.1:53: i/o timeout`
- From K3s node: `ping 1.1.1.1` → 100% packet loss
- RPi4 itself has internet (ping works from rpi4), but LAN clients (172.16.1.0/24) don't

### Root Cause

RPi4 USB Ethernet adapters use predictable names based on MAC address (`enxMACMACMAC`).
If the adapter or its MAC changes, `/etc/nftables.conf` masquerade rule references a non-existent interface → NAT silently stops working → K3s nodes on 172.16.1.0/24 can't reach the internet.

```bash
# Broken config (hardcoded interface name)
oifname "enx00e04c690e15" masquerade   # ← interface doesn't exist

# Actual interface
ip link show | grep enx
# enx00249b1b0d6b   ← different MAC = different name
```

### Fix (permanent, generic)

```bash
# Use wildcard — matches ANY USB Ethernet adapter
sudo sed -i 's/oifname "enx[^"]*"/oifname "enx*"/' /etc/nftables.conf

# Reload
sudo nft flush ruleset
sudo nft -f /etc/nftables.conf

# Verify
sudo nft list table inet nat
# Should show: oifname "enx*" masquerade

# Ensure nftables starts on boot
sudo systemctl enable nftables
```

### Verification

```bash
# From K3s node (172.16.1.10):
ping -c2 1.1.1.1           # should work
nslookup registry-1.docker.io  # should resolve

# From K3s cluster:
kubectl get pods -n kubelab  # ErrImagePull → Running (kubelet retries)
```

### Prevention

- **Never hardcode `enx*` interface names** in config files. Always use wildcards or stable names.
- The `enx*` naming comes from systemd predictable names for USB adapters (based on MAC).
- If you need a stable name, create a udev rule: `SUBSYSTEM=="net", ATTR{address}=="XX:XX:XX:XX:XX:XX", NAME="usbwan0"`
- Check `sudo systemctl is-enabled nftables` — must be `enabled` for rules to survive reboot.

### Related

- [headscale-setup](../runbooks/headscale-setup.md#incident-rpi4-dns-boot-race) — same RPi4 gateway, different DNS failure mode
- HW-019: USB Ethernet MAC mismatch (netplan fixed, nftables missed)

---

## DNS Resolution Failures

### Problem

Services are unreachable by domain name.

### Diagnostic Steps

```bash
# Test DNS resolution
dig api.kubelab.live
dig staging.kubelab.live
nslookup web.kubelab.live

# Check /etc/hosts for local overrides
cat /etc/hosts | grep kubelab

# Verify DNS propagation
dig +trace kubelab.live
```

### Solution

```bash
# For local development, add to /etc/hosts
echo "127.0.0.1 api.localhost web.localhost blog.localhost" | sudo tee -a /etc/hosts

# For staging (KubeLab), ensure WireGuard is connected
sudo wg show

# Restart CoreDNS if DNS gateway issues
toolkit edge restart dns-gateway

# Flush local DNS cache
sudo systemd-resolve --flush-caches   # Ubuntu/Debian
sudo dscacheutil -flushcache           # macOS
```

### Prevention

- Always verify DNS before deploying: `make verify-dns ENVIRONMENT=prod`
- Use `.localhost` for development, avoid real domains
- Document all DNS changes in infrastructure changelog

## Traefik Routing Issues

### Problem

404/502 errors from Traefik reverse proxy.

### Diagnostic Steps

```bash
# Check Traefik dashboard
toolkit edge logs traefik | grep error

# Verify router configuration
docker exec traefik-container cat /etc/traefik/dynamic/app-api.yml

# Check service discovery
curl http://localhost:8080/api/http/services   # Traefik API
```

### Solution

```bash
# Regenerate Traefik configs
ENVIRONMENT=dev toolkit config generate

# Restart Traefik
toolkit edge restart traefik

# Verify container labels
docker inspect api-container | grep traefik

# Test backend directly (bypass Traefik)
docker exec -it api-container curl localhost:8080/health
```

### Prevention

- Always validate compose files: `docker compose config`
- Use `traefik.http.services.<name>.loadbalancer.healthcheck` in production
- Monitor Traefik metrics in Grafana

## Network Connectivity Problems

### Problem

Containers cannot communicate with each other on the Docker network.

### Diagnostic Steps

```bash
# Check Docker networks
docker network inspect mlorente-network

# Verify container network attachment
docker inspect api-container | grep -A 10 Networks

# Test inter-container connectivity
docker exec web-container ping api-container
docker exec api-container curl http://postgres-container:5432
```

### Solution

```bash
# Recreate Docker network
docker network rm mlorente-network
docker network create mlorente-network

# Restart affected services
toolkit apps down api && toolkit apps up api

# Check firewall rules
sudo iptables -L -n | grep DOCKER
sudo ufw status

# For staging/prod, verify WireGuard tunnel
ping 10.0.0.1   # WireGuard gateway
```

### Prevention

- Use explicit network definitions in compose files
- Document network architecture
- Test cross-service communication in CI/CD

## Timeout Errors

### Problem

Request timeouts and slow responses between services.

### Diagnostic Steps

```bash
# Check timeout configurations
grep -r "timeout" infra/compose/
grep -r "timeout" edge/traefik/templates/

# Monitor response times
curl -w "@curl-format.txt" -o /dev/null -s https://api.kubelab.live/health

# Check load and network latency
ping -c 10 api.kubelab.live
mtr api.kubelab.live
```

### Solution

```bash
# Increase Traefik timeouts (edge/traefik/templates/middlewares.template.yml)
# Adjust forwardedHeaders.trustedIPs timeout settings

# For Nginx caching issues
toolkit edge restart nginx

# Check backend health
toolkit apps logs api --no-follow | grep "slow query"

# Database connection pool exhaustion
docker exec postgres-container psql -c "SELECT * FROM pg_stat_activity;"
```

### Prevention

- Set reasonable timeouts: 30s for API, 120s for long-running ops
- Implement proper health checks on all services
- Monitor P95/P99 latency in Grafana
