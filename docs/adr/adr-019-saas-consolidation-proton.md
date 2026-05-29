---
id: adr-019-saas-consolidation-proton
type: adr
status: active
created: "2026-03-10"
owner: manu
---

# ADR-019: SaaS Consolidation — Proton Unlimited + Google Downgrade

## Status

Accepted 2026-03-10

## Context

Current SaaS stack for personal productivity and infrastructure has cost overlap and fragmentation across multiple providers:

- **Google One 2TB** ($9.99/month) — Drive, Photos, Calendar, Meet
- **Proton VPN Plus** ($7/month) — privacy VPN
- **Zoho Mail Lite** ($1/month) — email hosting for `mlorente.dev`
- **Squarespace** (~$35/year) — domain registrar

Total: ~$17.99/month ($215.88/year)

Additionally, Stream CLOUD (Nextcloud + Immich) is planned to self-host file sync and photo management, which will further reduce reliance on Google.

## Decision

**Consolidate into Proton Unlimited + downgraded Google One:**

1. **Proton Unlimited** (~$10/month) — replaces Proton VPN Plus + Zoho Mail. Includes: VPN, Mail (custom domains), Drive (500GB), Calendar.
2. **Google One 200GB** ($30/year / $2.50/month) — retained for Google Photos + occasional Docs/Sheets editing.
3. **Migrate `mlorente.dev` email** from Zoho Mail to Proton Mail (update MX, DKIM, SPF, DMARC in Cloudflare).
4. **Cancel Zoho Mail Lite** after migration.
5. **Cancel Proton VPN Plus** (included in Unlimited).
6. **Transfer domains** from Squarespace to Cloudflare Registrar (OPS-010, at-cost pricing).

### Storage strategy

| Provider | Purpose | Capacity |
|---|---|---|
| Proton Drive | Document storage (primary) | 500GB |
| Google Drive | Photos + light doc editing | 200GB |
| Nextcloud (future) | Self-hosted file sync | Unlimited (SSD) |
| Immich (future) | Self-hosted photos | Unlimited (SSD) |

### Migration sequence

**Deadline: 2026-08-20** (Zoho Mail Lite license expiration)

1. Contract Proton Unlimited
2. Migrate `mlorente.dev` MX from Zoho to Proton (Cloudflare DNS records)
3. Move documents from Google Drive to Proton Drive
4. Cancel Zoho Mail Lite (before 2026-08-20)
5. Cancel Proton VPN Plus
6. Downgrade Google One from 2TB to 200GB
7. (Later) Deploy Immich → migrate photos → evaluate cancelling Google entirely

## Cost comparison

### Before

| Service | Monthly | Annual |
|---|---|---|
| Google One 2TB | $9.99 | $119.88 |
| Proton VPN Plus | $7.00 | $84.00 |
| Zoho Mail Lite | $1.00 | $12.00 |
| **Total** | **$17.99** | **$215.88** |

### After

| Service | Monthly | Annual |
|---|---|---|
| Proton Unlimited | $10.00 | $120.00 |
| Google One 200GB | $2.50 | $30.00 |
| **Total** | **$12.50** | **$150.00** |

### Savings: ~$5.50/month ($66/year)

Post-Immich (future): Google One cancelable entirely → **$10/month ($120/year)**, saving $96/year total.

## Consequences

### Positive
- Fewer providers (3 → 2)
- E2E encryption on documents (Proton Drive)
- Unified VPN + email + storage under one privacy-focused provider
- Path to full Google independence when Immich + Nextcloud are operational

### Negative
- Proton Drive has no online document editing (Docs/Sheets stay on Google)
- Email migration requires DNS changes and DKIM/SPF/DMARC reconfiguration
- Proton Calendar is less featured than Google Calendar

### Risks
- Do NOT downgrade Google to 200GB before confirming current usage fits
- Verify Beehiiv/SendGrid email chain is independent of Zoho before cancelling
