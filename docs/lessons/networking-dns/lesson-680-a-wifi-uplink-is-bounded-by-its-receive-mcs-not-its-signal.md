---
id: lesson-680-a-wifi-uplink-is-bounded-by-its-receive-mcs-not-its-signal
type: lesson
status: active
created: "2026-10-31"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, edge, wifi, shaping]
---

# A Wi-Fi uplink is bounded by its receive MCS, not its signal

**Context**: The lab edge's uplink moved from a site's free Wi-Fi plan to a paid one advertised as four times faster. With the CAKE shaper lifted, the line still read about 4.8 Mbit/s down.

**Problem**: The signal looked good, -57 dBm in a scan, so the band was not suspected. `iw dev uplink0 link` showed the real bound: the adapter received at MCS 1, 13 Mbit/s PHY, on 2.4 GHz channel 1, while it transmitted at MCS 14. Signal strength does not show interference. A shared 2.4 GHz band at a hotel, plus the edge's own lab AP on 2.4 GHz a few centimetres away, lowers the SNR and with it the receive rate. Two other readings would have pointed the wrong way. A client's own download rate counts only that client, and a single speed-test server can be the bound itself: one read 14 Mbit/s from both the edge and a laptop behind it, while another read 27.

**Solution**: The site's APs also served 5 GHz. The scan showed it at -67 dBm, weaker than 2.4 GHz. The new site key `networking.edge.uplink.band: "5GHz"` renders netplan's `band:`, which reaches wpa_supplicant as `freq_list`. The adapter re-associated at VHT-MCS 8 (78 Mbit/s PHY), and the line read 27 Mbit/s down. The shaper was set to 90% of that (#2875).

**Rule**: When a Wi-Fi link is slow, read `rx bitrate` and its MCS before the dBm. A low MCS at good signal means interference, and changing band beats changing position or power. Keep an uplink and an AP on one host on different bands. Measure a line on the uplink adapter's own `rx_bytes`/`tx_bytes`, which sit before the ingress IFB, with the shaper lifted. Use parallel streams for the whole window and at least two servers.

**Tags**: `#wifi` `#cake` `#pr-2875` `#issue-2876`
