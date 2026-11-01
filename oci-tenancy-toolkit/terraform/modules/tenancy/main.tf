terraform {
  required_providers {
    oci = { source = "oracle/oci" }
  }
}

variable "tenancy_ocid" { type = string }

data "oci_identity_tenancy" "this" { tenancy_id = var.tenancy_ocid }
data "oci_identity_region_subscriptions" "this" { tenancy_id = var.tenancy_ocid }

data "oci_identity_compartments" "all" {
  compartment_id            = var.tenancy_ocid
  compartment_id_in_subtree = true
  access_level              = "ANY"
  state                     = "ACTIVE"
}

locals {
  compartments = concat([{
    id             = var.tenancy_ocid
    name           = data.oci_identity_tenancy.this.name
    compartment_id = null
    state          = "ACTIVE"
    description    = "Tenancy root"
    }], [for c in data.oci_identity_compartments.all.compartments : {
    id             = c.id
    name           = c.name
    compartment_id = c.compartment_id
    state          = c.state
    description    = c.description
  }])
}

data "oci_identity_policies" "all" {
  for_each       = toset([for c in local.compartments : c.id])
  compartment_id = each.key
  state          = "ACTIVE"
}

output "tenancy" {
  value = { id = var.tenancy_ocid, name = data.oci_identity_tenancy.this.name }
}
output "regions" {
  value = [for r in data.oci_identity_region_subscriptions.this.region_subscriptions : {
    region_name = r.region_name, region_key = r.region_key, is_home_region = r.is_home_region, status = r.state
  }]
}
output "compartments" { value = local.compartments }
output "policies" {
  value = flatten([for ds in data.oci_identity_policies.all : [for p in ds.policies : {
    id             = p.id
    name           = p.name
    compartment_id = p.compartment_id
    description    = p.description
    statements     = p.statements
  }]])
}
