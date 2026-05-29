---
id: "kubelab-infra-dns-cloudflare"
type: architecture
status: active
tags: [infrastructure, kubelab]
created: "2026-02-07"
owner: manu
---

;;  
;; Domain:     mlorente.dev.  
;; Exported:   2025-08-30 04:18:04  
;;  
;; This file is intended for use for informational and archival  
;; purposes ONLY and MUST be edited before use on a production  
;; DNS server.  In particular, you must:  
;;   \-- update the SOA record with the correct authoritative name server  
;;   \-- update the SOA record with the contact e-mail address information  
;;   \-- update the NS record(s) with the authoritative name servers for this domain.  
;;  
;; For further information, please consult the BIND documentation  
;; located on the following website:  
;;  
;; http://www.isc.org/  
;;  
;; And RFC 1035:  
;;  
;; http://www.ietf.org/rfc/rfc1035.txt  
;;  
;; Please note that we do NOT offer technical support for any use  
;; of this zone data, the BIND name server, or any other third-party  
;; DNS software.  
;;  
;; Use at your own risk.  
;; SOA Record  
mlorente.dev	3600	IN	SOA	denver.ns.cloudflare.com. dns.cloudflare.com. 2050819408 10000 2400 604800 3600

;; NS Records  
mlorente.dev.	86400	IN	NS	denver.ns.cloudflare.com.  
mlorente.dev.	86400	IN	NS	vita.ns.cloudflare.com.

;; A Records  
api.mlorente.dev.	300	IN	A	162.55.57.175 ; cf\_tags=cf-proxied:false  
grafana.mlorente.dev.	300	IN	A	162.55.57.175 ; cf\_tags=cf-proxied:false  
loki.mlorente.dev.	300	IN	A	162.55.57.175 ; cf\_tags=cf-proxied:false  
minio.mlorente.dev.	300	IN	A	162.55.57.175 ; cf\_tags=cf-proxied:false  
mlorente.dev.	300	IN	A	162.55.57.175 ; cf\_tags=cf-proxied:false  
n8n.mlorente.dev.	300	IN	A	162.55.57.175 ; cf\_tags=cf-proxied:false  
portainer.mlorente.dev.	300	IN	A	162.55.57.175 ; cf\_tags=cf-proxied:false  
status.mlorente.dev.	300	IN	A	162.55.57.175 ; cf\_tags=cf-proxied:false  
traefik.mlorente.dev.	300	IN	A	162.55.57.175 ; cf\_tags=cf-proxied:false  
web.mlorente.dev.	300	IN	A	162.55.57.175 ; cf\_tags=cf-proxied:false  
wiki.mlorente.dev.	300	IN	A	162.55.57.175 ; cf\_tags=cf-proxied:false

;; CNAME Records  
2e82.\_domainkey.mlorente.dev.	300	IN	CNAME	2e82.domainkey.u50481429.wl180.sendgrid.net. ; cf\_tags=cf-proxied:false  
2e8.\_domainkey.mlorente.dev.	300	IN	CNAME	2e8.domainkey.u50481429.wl180.sendgrid.net. ; cf\_tags=cf-proxied:false  
50481429.mlorente.dev.	300	IN	CNAME	sendgrid.net. ; cf\_tags=cf-proxied:false  
elink52d.mlorente.dev.	300	IN	CNAME	branded-link.beehiiv.com. ; cf\_tags=cf-proxied:false  
em6406.mlorente.dev.	300	IN	CNAME	u50481429.wl180.sendgrid.net. ; cf\_tags=cf-proxied:false  
mail.mlorente.dev.	300	IN	CNAME	mail.cs.zohohost.com. ; cf\_tags=cf-proxied:false  
newsletter.mlorente.dev.	300	IN	CNAME	cname.beehiiv.com. ; cf\_tags=cf-proxied:false  
zb44344374.mlorente.dev.	600	IN	CNAME	zmverify.zoho.com. ; cf\_tags=cf-proxied:false

;; MX Records  
mlorente.dev.	600	IN	MX	50 mx3.zoho.com.  
mlorente.dev.	600	IN	MX	10 mx.zoho.com.  
mlorente.dev.	600	IN	MX	20 mx2.zoho.com.

;; TXT Records  
\_acme-challenge.mlorente.dev.	300	IN	TXT	"T8wleiT4rng4OH85buC2F4YKbMp2YxnmcJp19WWhH80"  
\_acme-challenge.mlorente.dev.	300	IN	TXT	"4wwWgvNwv1VumRuiUFYgehfUylWFWZYXAKlJ3UUH1RA"  
\_acme-challenge.mlorente.dev.	300	IN	TXT	"602D0DRDTJbeCigx5VIp9apTO\_-MolOugl1zZ9PssWQ"  
\_acme-challenge.mlorente.dev.	300	IN	TXT	"tgVOv3JpU\_M9g7Gao6hHLpljPUYP8ojVddcqiylcJ18"  
\_dmarc.mlorente.dev.	300	IN	TXT	"v=DMARC1; p=quarantine; rua=mailto:mlorentedev@gmail.com; ruf=mailto:mlorentedev@gmail.com; sp=quarantine; adkim=r; aspf=r"  
mlorente.dev.	300	IN	TXT	"v=spf1 include:zohomail.com \~all"  
mlorente.dev.	300	IN	TXT	"google-site-verification=-JcGwi5aesZrFESM5OHp0MwM9ZlKOxNAuBhOw6M8DP8"  
mlorente.dev.	300	IN	TXT	"openai-domain-verification=dv-ufyfgYhYBdJrdml1AYDvkHoo"  
zmail.\_domainkey.mlorente.dev.	600	IN	TXT	"v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCHorSmTdjuaFvUQ28Xdcm6nN+Pos4WW0o47seQDEnlhwR/sfpPGDNr3nMYjLQUHZcusRzYDFM65NK6Pzk2hYBzrfb1XM22zqB0H6lYiSD+Ra+O9V42FFeDbZY/NKbwIyb34pET2dbxfs/m27Jnpd1OjpyBmUfoiARk/pW1/HApdwIDAQAB"
