---
id: lesson-078-2026-02-27-cloudflare-terraform-import-use-fq
type: lesson
status: active
created: "2026-05-01"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# 2026-02-27 — Cloudflare Terraform Import: Use FQDN for Root Records, Not @

**Context:** Importing existing Cloudflare DNS records into Terraform state (`terraform import`).

**Problem:** Defined root records as `name = "@"` in `.tf` files. After import, `terraform plan` showed `forces replacement` on both root records — name changed from `kubelab.live` → `@`. Cloudflare stores the FQDN in the API/state, not the `@` alias. The replacement would delete and recreate the record, causing a brief DNS outage.

**Solution:** Use the FQDN in the Terraform config:
```hcl
resource "cloudflare_record" "kubelab_root" {
  name = "kubelab.live"  # NOT "@"
}
```

**Rule:** When importing existing Cloudflare records, always use the FQDN for root records (not `@`). Check the imported state with `terraform state show` to see what Cloudflare actually stores, then match your `.tf` to that.

---
