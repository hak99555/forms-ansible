terraform {
  required_providers {
    oci = { source = "oracle/oci" }
  }
}

variable "tenancy_ocid" { type = string }
variable "compartment_ids" { type = set(string) }
variable "domain_compartment_ids" { type = set(string) }
variable "region" { type = string }
variable "services" { type = set(string) }
variable "bucket_details" { type = bool }
variable "include_identity_domains" { type = bool }

data "oci_database_autonomous_databases" "all" {
  for_each       = contains(var.services, "adb") ? var.compartment_ids : toset([])
  compartment_id = each.key
}

data "oci_integration_integration_instances" "all" {
  for_each       = contains(var.services, "oic") ? var.compartment_ids : toset([])
  compartment_id = each.key
}

data "oci_objectstorage_namespace" "this" {
  count          = contains(var.services, "buckets") ? 1 : 0
  compartment_id = var.tenancy_ocid
}

data "oci_objectstorage_bucket_summaries" "all" {
  for_each       = contains(var.services, "buckets") ? var.compartment_ids : toset([])
  compartment_id = each.key
  namespace      = data.oci_objectstorage_namespace.this[0].namespace
}

locals {
  buckets = flatten([for ds in data.oci_objectstorage_bucket_summaries.all : ds.bucket_summaries])
}

data "oci_objectstorage_bucket" "details" {
  for_each  = { for b in local.buckets : b.name => b if var.bucket_details }
  namespace = data.oci_objectstorage_namespace.this[0].namespace
  name      = each.key
}

# Domains can be homed outside the tenancy home region. Discover in each scanned region.
data "oci_identity_domains" "all" {
  for_each       = var.include_identity_domains ? var.domain_compartment_ids : toset([])
  compartment_id = each.key
}

output "domains" {
  value = flatten([for ds in data.oci_identity_domains.all : [for d in ds.domains : {
    id = d.id, name = d.display_name, url = d.url, home_region = d.home_region, compartment_id = d.compartment_id, state = d.state
  }]])
}

output "resources" {
  value = concat(
    flatten([for ds in data.oci_database_autonomous_databases.all : [for r in ds.autonomous_databases : {
      kind          = "adb", id = r.id, name = r.display_name, compartment_id = r.compartment_id, region = var.region, state = r.state
      freeform_tags = r.freeform_tags, defined_tags = r.defined_tags
      details = {
        db_name                  = r.db_name, db_workload = r.db_workload, db_version = r.db_version
        compute_model            = r.compute_model, compute_count = r.compute_count, cpu_core_count = r.cpu_core_count
        data_storage_size_in_tbs = r.data_storage_size_in_tbs, is_auto_scaling_enabled = r.is_auto_scaling_enabled
        is_dedicated             = r.is_dedicated, is_free_tier = r.is_free_tier, is_mtls_connection_required = r.is_mtls_connection_required
        private_endpoint         = r.private_endpoint, subnet_id = r.subnet_id, nsg_ids = r.nsg_ids
        whitelisted_ips          = r.whitelisted_ips, is_access_control_enabled = r.is_access_control_enabled
        lifecycle_details        = r.lifecycle_details
      }
    }]]),
    flatten([for ds in data.oci_integration_integration_instances.all : [for r in ds.integration_instances : {
      kind          = "oic", id = r.id, name = r.display_name, compartment_id = r.compartment_id, region = var.region, state = r.state
      freeform_tags = r.freeform_tags, defined_tags = r.defined_tags
      details = {
        integration_instance_type = r.integration_instance_type, instance_url = r.instance_url
        message_packs             = r.message_packs, is_byol = r.is_byol, network_endpoint_details = r.network_endpoint_details
        lifecycle_details         = r.lifecycle_details
      }
    }]]),
    [for r in local.buckets : {
      kind          = "bucket", id = "${var.region}/${r.namespace}/${r.name}", name = r.name, compartment_id = r.compartment_id, region = var.region, state = null
      freeform_tags = r.freeform_tags, defined_tags = r.defined_tags
      details = {
        namespace             = r.namespace, details_collected = var.bucket_details
        public_access_type    = var.bucket_details ? data.oci_objectstorage_bucket.details[r.name].access_type : null
        versioning            = var.bucket_details ? data.oci_objectstorage_bucket.details[r.name].versioning : null
        storage_tier          = var.bucket_details ? data.oci_objectstorage_bucket.details[r.name].storage_tier : null
        kms_key_id            = var.bucket_details ? data.oci_objectstorage_bucket.details[r.name].kms_key_id : null
        approximate_count     = var.bucket_details ? data.oci_objectstorage_bucket.details[r.name].approximate_count : null
        approximate_size      = var.bucket_details ? data.oci_objectstorage_bucket.details[r.name].approximate_size : null
        object_events_enabled = var.bucket_details ? data.oci_objectstorage_bucket.details[r.name].object_events_enabled : null
      }
    }]
  )
}
