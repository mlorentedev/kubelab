# Cloudflare R2: one backup bucket per node, each under a lock no node can lift
# (BACKUP-057).
#
# Read this before editing:
#
# - Node buckets come from backup.sources in common.yaml, rendered into r2.tfvars
#   by the runner (toolkit/features/r2_tfvars.py). Never add a node here by hand.
# - The lock rule refuses deletes of objects younger than R under data/,
#   snapshots/, keys/ and config. locks/ and index/ stay out on purpose: restic
#   deletes them on every run (tests/test_r2_terraform.py).
# - Node buckets and locks carry prevent_destroy. Removing a node from the SSOT
#   therefore fails the plan instead of deleting its backups; take it out of
#   state deliberately, after its data is no longer needed.
# - The product documents bucket (STOR-002) is declared by hand below: it is
#   not a backup, so it stays out of the rendered node map.
# - The scratch pair exists only for the PR 2 measurement and is destroyable.
#   prevent_destroy cannot depend on a variable, so it lives outside the map.
# - A separate root from infra/terraform/dns/ because R2 bucket locks need
#   provider v5, and the DNS root stays on ~> 4.0 until it is migrated.

terraform {
  required_version = ">= 1.10"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.8"
    }
  }

  # Shared settings: ../backend.s3.tfbackend, passed by the runner (TF-007).
  backend "s3" {
    key = "r2/terraform.tfstate"
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

locals {
  # Keyed by id so the list comes out in id order, which is how the API returns
  # the rules. In prefix order every plan would show a reorder against state.
  lock_rules = [
    for id, prefix in { for p in var.locked_prefixes : "retain-${trimsuffix(p, "/")}" => p } : {
      id      = id
      enabled = true
      prefix  = prefix
      condition = {
        type            = "Age"
        max_age_seconds = var.lock_max_age_seconds
      }
    }
  ]
}

# ---------------------------------------------------------------------------
# Node buckets
# ---------------------------------------------------------------------------

resource "cloudflare_r2_bucket" "node" {
  for_each = var.node_buckets

  account_id = var.account_id
  name       = each.value

  lifecycle {
    prevent_destroy = true
  }
}

resource "cloudflare_r2_bucket_lock" "node" {
  for_each = var.node_buckets

  account_id  = var.account_id
  bucket_name = cloudflare_r2_bucket.node[each.key].name
  rules       = local.lock_rules

  lifecycle {
    prevent_destroy = true
  }
}

# ---------------------------------------------------------------------------
# Product documents (STOR-002, #2535): private copies of the public documents
# a product cites, kept as evidence and never served.
#
# - The lock is an Age rule, never Indefinite (operator, 2026-11-02). It
#   refuses a delete or overwrite under sources/ for 30 days, so a mistake is
#   recoverable, and a document can still be withdrawn after that (takedown).
# - Writes are create-only by convention of the uploader, which keys objects
#   by their sha256; nothing here enforces it.
# - The name is mirrored by DOCUMENTS_BUCKET in
#   toolkit/features/r2_documents_token.py, whose token is minted outside
#   Terraform so that no state file holds a copy of it.
# ---------------------------------------------------------------------------

resource "cloudflare_r2_bucket" "documents" {
  account_id = var.account_id
  name       = "kubelab-product-documents"

  lifecycle {
    prevent_destroy = true
  }
}

resource "cloudflare_r2_bucket_lock" "documents" {
  account_id  = var.account_id
  bucket_name = cloudflare_r2_bucket.documents.name
  rules = [
    {
      id      = "retain-sources"
      enabled = true
      prefix  = "sources/"
      condition = {
        type            = "Age"
        max_age_seconds = 30 * 86400
      }
    }
  ]

  lifecycle {
    prevent_destroy = true
  }
}

# ---------------------------------------------------------------------------
# Scratch pair: the measurement bucket (specs/BACKUP-057/tasks.md, PR 2).
# ---------------------------------------------------------------------------

resource "cloudflare_r2_bucket" "scratch" {
  count = var.scratch ? 1 : 0

  account_id = var.account_id
  name       = var.scratch_bucket
}

resource "cloudflare_r2_bucket_lock" "scratch" {
  count = var.scratch ? 1 : 0

  account_id  = var.account_id
  bucket_name = cloudflare_r2_bucket.scratch[0].name
  rules = [
    for rule in local.lock_rules : merge(rule, {
      condition = merge(rule.condition, { max_age_seconds = var.scratch_max_age_seconds })
    })
  ]
}
