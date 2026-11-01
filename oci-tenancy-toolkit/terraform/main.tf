module "tenancy" {
  source       = "./modules/tenancy"
  providers    = { oci = oci.home }
  tenancy_ocid = var.tenancy_ocid
}

locals {
  active_ids = toset([for c in module.tenancy.compartments : c.id])
  scan_ids   = length(var.compartment_ids) == 0 ? local.active_ids : var.compartment_ids
}

module "regional" {
  source                   = "./modules/regional"
  tenancy_ocid             = var.tenancy_ocid
  compartment_ids          = local.scan_ids
  domain_compartment_ids   = local.active_ids
  region                   = var.region
  services                 = var.services
  bucket_details           = var.bucket_details
  include_identity_domains = var.include_identity_domains
}

module "identity_domain" {
  for_each = {
    for d in module.regional.domains : d.id => d
    if d.state == "ACTIVE" && (length(var.domain_ids) == 0 || contains(var.domain_ids, d.id))
  }
  source     = "./modules/identity-domain"
  domain     = each.value
  user_names = lookup(var.user_queries, each.key, toset([]))
}

output "inventory" {
  description = "Read-only inventory; export using terraform output -json inventory. Contains administrative metadata."
  sensitive   = true
  value = {
    schema_version = 1
    collected_at   = timestamp()
    tenancy        = module.tenancy.tenancy
    regions        = module.tenancy.regions
    compartments   = module.tenancy.compartments
    policies       = module.tenancy.policies
    domains        = module.regional.domains
    groups         = flatten([for d in module.identity_domain : d.groups])
    users          = flatten([for d in module.identity_domain : d.users])
    memberships    = flatten([for d in module.identity_domain : d.memberships])
    resources      = module.regional.resources
    coverage = {
      regions              = [var.region]
      services             = sort(tolist(var.services))
      compartment_ids      = sort(tolist(local.scan_ids))
      domain_ids           = sort(keys(module.identity_domain))
      identity_domains     = var.include_identity_domains
      bucket_details       = var.bucket_details
      user_queries         = var.user_queries
      policies             = "root-and-all-active-compartments"
      membership_semantics = "direct-scim-members-filter"
      incomplete           = false
    }
  }
  precondition {
    condition     = length(setsubtract(local.scan_ids, local.active_ids)) == 0
    error_message = "compartment_ids contains an unknown or inactive compartment."
  }
  precondition {
    condition     = contains([for r in module.tenancy.regions : r.region_name if r.is_home_region], var.home_region)
    error_message = "home_region does not match the tenancy home region."
  }
  precondition {
    condition     = contains([for r in module.tenancy.regions : r.region_name if r.status == "READY"], var.region)
    error_message = "region must be a READY tenancy subscription."
  }
  precondition {
    condition     = length(setsubtract(var.domain_ids, toset(keys(module.identity_domain)))) == 0
    error_message = "A requested domain was not found ACTIVE in this region; use its home/replica region."
  }
  precondition {
    condition     = length(setsubtract(toset(keys(var.user_queries)), toset(keys(module.identity_domain)))) == 0
    error_message = "Every user_queries domain must be selected and ACTIVE in this region."
  }
}
