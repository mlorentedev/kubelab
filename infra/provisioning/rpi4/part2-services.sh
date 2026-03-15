#!/usr/bin/env bash
# =============================================================================
# KubeLab RPi 4 Provisioning — Part 2: Services
# =============================================================================
# Run as user manu after Part 1 reboot.
#
#   ssh manu@<IP>
#   bash part2-services.sh
# =============================================================================
set -euo pipefail

HEADSCALE_URL="https://vpn.kubelab.live"
TAILSCALE_FLAGS="--login-server=${HEADSCALE_URL} --accept-dns=false --advertise-routes=172.16.1.0/24"
COREDNS_DIR="${HOME}/coredns"

echo "=== KubeLab RPi 4 Provisioning — Part 2: Services ==="
echo ""

# ---------------------------------------------------------------------------
# 1. Docker Engine
# ---------------------------------------------------------------------------
echo "[1/5] Installing Docker..."
if command -v docker &>/dev/null; then
    echo "  Already installed: $(docker --version)"
else
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "${USER}"
    sudo systemctl enable docker
    sudo systemctl start docker
    echo "  OK: $(docker --version)"
fi

# ---------------------------------------------------------------------------
# 2. Tailscale
# ---------------------------------------------------------------------------
echo "[2/5] Installing Tailscale..."
if command -v tailscale &>/dev/null; then
    echo "  Already installed: $(tailscale version | head -1)"
else
    curl -fsSL https://tailscale.com/install.sh | sudo sh
    echo "  OK: Tailscale installed"
fi

# Ensure tailscaled starts after Docker
sudo mkdir -p /etc/systemd/system/tailscaled.service.d
cat <<'EOF' | sudo tee /etc/systemd/system/tailscaled.service.d/after-docker.conf > /dev/null
[Unit]
After=docker.service
Wants=docker.service
EOF
sudo systemctl daemon-reload

TS_STATUS=$(sudo tailscale status 2>&1 || true)
if echo "${TS_STATUS}" | grep -q "100.64.0"; then
    echo "  Tailscale already connected"
else
    echo ""
    echo "  ================================================================"
    echo "  Tailscale registration required. Run manually:"
    echo ""
    echo "    sudo tailscale up ${TAILSCALE_FLAGS} --authkey=<KEY>"
    echo ""
    echo "  Generate key on VPS:"
    echo "    docker exec headscale headscale preauthkeys create --user kubelab --reusable --expiration 24h"
    echo "  ================================================================"
    echo ""
fi

# ---------------------------------------------------------------------------
# 3. Lock resolv.conf
# ---------------------------------------------------------------------------
echo "[3/5] Locking resolv.conf..."
sudo chattr -i /etc/resolv.conf 2>/dev/null || true
printf "nameserver 127.0.0.1\nnameserver 8.8.8.8\n" | sudo tee /etc/resolv.conf > /dev/null
sudo chattr +i /etc/resolv.conf
echo "  OK: resolv.conf locked"

# ---------------------------------------------------------------------------
# 4. Pi-hole + CoreDNS
# ---------------------------------------------------------------------------
echo "[4/5] Deploying Pi-hole + CoreDNS..."

mkdir -p "${COREDNS_DIR}"

# Copy configs from repo if available, otherwise use embedded
REPO_DNS="${HOME}/Projects/kubelab/edge/dns-gateway"
if [ -d "${REPO_DNS}" ]; then
    cp "${REPO_DNS}/Corefile" "${COREDNS_DIR}/Corefile"
    cp "${REPO_DNS}/compose.base.yml" "${COREDNS_DIR}/compose.base.yml"
    cp "${REPO_DNS}/pihole-forwarding.conf" "${COREDNS_DIR}/pihole-forwarding.conf"
    echo "  Copied configs from repo"
else
    echo "  Repo not found, using embedded configs..."

    cat > "${COREDNS_DIR}/Corefile" <<'COREFILE'
staging.kubelab.live {
    hosts {
        100.64.0.4 staging.kubelab.live
        100.64.0.4 api.staging.kubelab.live
        100.64.0.4 web.staging.kubelab.live
        100.64.0.4 blog.staging.kubelab.live
        100.64.0.4 grafana.staging.kubelab.live
        100.64.0.4 traefik.staging.kubelab.live
        100.64.0.4 auth.staging.kubelab.live
        100.64.0.4 status.staging.kubelab.live
        100.64.0.4 gitea.staging.kubelab.live
        100.64.0.4 n8n.staging.kubelab.live
        100.64.0.4 minio.staging.kubelab.live
        100.64.0.4 console.minio.staging.kubelab.live
        100.64.0.4 loki.staging.kubelab.live
        100.64.0.4 portainer.staging.kubelab.live
        fallthrough
    }
    template IN A staging.kubelab.live {
        match .*\.staging\.kubelab\.live
        answer "{{ .Name }} 60 IN A 100.64.0.4"
        fallthrough
    }
    log
    errors
}

kubelab.live {
    hosts {
        100.64.0.6 status.kubelab.live
        100.64.0.3 ollama.kubelab.live
        100.64.0.8 jetson.kubelab.live
        100.64.0.2 kubelab.live
        100.64.0.2 api.kubelab.live
        100.64.0.2 web.kubelab.live
        100.64.0.2 blog.kubelab.live
        100.64.0.2 auth.kubelab.live
        100.64.0.2 grafana.kubelab.live
        100.64.0.2 loki.kubelab.live
        100.64.0.2 gitea.kubelab.live
        100.64.0.2 n8n.kubelab.live
        100.64.0.2 minio.kubelab.live
        100.64.0.2 console.minio.kubelab.live
        162.55.57.175 vpn.kubelab.live
        fallthrough
    }
    forward . 1.1.1.1 8.8.8.8
    log
    errors
}

. {
    forward . 1.1.1.1 8.8.8.8
    cache 30
    log
    errors
}
COREFILE

    cat > "${COREDNS_DIR}/pihole-forwarding.conf" <<'EOF'
server=/kubelab.live/172.17.0.1#5353
EOF

    cat > "${COREDNS_DIR}/compose.base.yml" <<'EOF'
services:
  pihole:
    container_name: pihole
    image: pihole/pihole:latest
    restart: unless-stopped
    ports:
      - "53:53/udp"
      - "53:53/tcp"
      - "80:80/tcp"
    volumes:
      - pihole_data:/etc/pihole
      - ./pihole-forwarding.conf:/etc/dnsmasq.d/pihole-forwarding.conf:ro
    environment:
      - TZ=America/Denver

  coredns:
    container_name: coredns
    image: coredns/coredns:1.12.1
    restart: unless-stopped
    ports:
      - "5353:53/udp"
      - "5353:53/tcp"
    volumes:
      - ./Corefile:/etc/coredns/Corefile:ro
    command: ["-conf", "/etc/coredns/Corefile"]

volumes:
  pihole_data:
EOF
fi

cd "${COREDNS_DIR}"
sudo docker compose -f compose.base.yml up -d

echo "  Waiting for Pi-hole to initialize (30s)..."
sleep 30

sudo docker exec pihole sed -i 's/etc_dnsmasq_d = false/etc_dnsmasq_d = true/' /etc/pihole/pihole.toml 2>/dev/null || true
sudo docker exec pihole sed -i 's/listeningMode = "LOCAL"/listeningMode = "ALL"/' /etc/pihole/pihole.toml 2>/dev/null || true
sudo docker restart pihole

echo "  OK: Pi-hole (port 53) + CoreDNS (port 5353) deployed"

# ---------------------------------------------------------------------------
# 5. Tailscale watchdog timer (auto-reconnect every 5 min)
# ---------------------------------------------------------------------------
echo "[5/5] Installing tailscale-watchdog timer..."

sudo tee /etc/systemd/system/tailscale-watchdog.service > /dev/null <<EOF
[Unit]
Description=Tailscale Watchdog — auto-reconnect to Headscale
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'STATUS=\$(tailscale status --self 2>&1 || true); if echo "\$STATUS" | grep -qE "stopped|NeedsLogin|NoState"; then tailscale up ${TAILSCALE_FLAGS}; fi'
EOF

sudo tee /etc/systemd/system/tailscale-watchdog.timer > /dev/null <<'EOF'
[Unit]
Description=Run Tailscale Watchdog every 5 minutes

[Timer]
OnBootSec=60
OnUnitActiveSec=300
AccuracySec=30

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now tailscale-watchdog.timer

echo "  OK: tailscale-watchdog.timer enabled"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "============================================="
echo "Part 2 complete."
echo "============================================="
echo "  Docker:     $(sudo docker --version 2>/dev/null)"
echo "  Tailscale:  $(tailscale version 2>/dev/null | head -1)"
echo "  Pi-hole:    port 53 + port 80 (admin)"
echo "  CoreDNS:    port 5353"
echo "  Watchdog:   every 5 min"
echo ""
echo "MANUAL STEPS:"
echo "  1. Register Tailscale:"
echo "     sudo tailscale up ${TAILSCALE_FLAGS} --authkey=<KEY>"
echo ""
echo "  2. Approve subnet route on VPS:"
echo "     docker exec headscale headscale nodes list"
echo "     docker exec headscale headscale nodes approve-routes -i <ID> --routes 172.16.1.0/24"
echo ""
echo "  3. Verify DNS:"
echo "     dig @127.0.0.1 -p 5353 api.staging.kubelab.live +short"
echo "     dig @127.0.0.1 vpn.kubelab.live +short"
echo "============================================="
