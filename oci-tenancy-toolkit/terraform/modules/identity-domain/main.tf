terraform {
  required_providers {
    oci = { source = "oracle/oci" }
  }
}

variable "domain" {
  type = object({ id = string, name = string, url = string })
}
variable "user_names" { type = set(string) }

# Never request all group members: nested member arrays have separate limits.
# The provider paginates the top-level SCIM Groups and Users collections.
data "oci_identity_domains_groups" "all" {
  idcs_endpoint = var.domain.url
  attributes    = "id,ocid,displayName"
}

data "oci_identity_domains_users" "selected" {
  count         = length(var.user_names) > 0 ? 1 : 0
  idcs_endpoint = var.domain.url
  attributes    = "id,ocid,userName,active"
  user_filter   = join(" or ", [for name in sort(tolist(var.user_names)) : "userName eq ${jsonencode(name)}"])
}

locals {
  users = length(var.user_names) > 0 ? data.oci_identity_domains_users.selected[0].users : []
}

data "oci_identity_domains_groups" "membership" {
  for_each      = { for u in local.users : u.id => u }
  idcs_endpoint = var.domain.url
  attributes    = "id,ocid,displayName"
  group_filter  = "members.value eq ${jsonencode(each.key)}"
}

output "groups" {
  value = [for g in data.oci_identity_domains_groups.all.groups : {
    id = g.id, ocid = g.ocid, name = g.display_name, domain_id = var.domain.id, domain_name = var.domain.name
  }]
}
output "users" {
  value = [for u in local.users : {
    id = u.id, ocid = u.ocid, name = u.user_name, active = u.active, domain_id = var.domain.id, domain_name = var.domain.name
  }]
  precondition {
    condition     = length(setsubtract(toset([for n in var.user_names : lower(n)]), toset([for u in local.users : lower(u.user_name)]))) == 0
    error_message = "At least one requested userName was not returned by the Identity Domain."
  }
}
output "memberships" {
  value = flatten([for uid, ds in data.oci_identity_domains_groups.membership : [for g in ds.groups : {
    domain_id = var.domain.id, user_id = uid, group_id = g.id, type = "direct"
  }]])
}
