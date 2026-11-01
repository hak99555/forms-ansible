variable "tenancy_ocid" {
  type        = string
  description = "Tenancy OCID, also the root compartment ID."
  validation {
    condition     = startswith(var.tenancy_ocid, "ocid1.tenancy.")
    error_message = "Provide an OCI tenancy OCID."
  }
}

variable "home_region" {
  type        = string
  description = "Tenancy home region for global IAM reads, e.g. ca-toronto-1."
}

variable "region" {
  type        = string
  description = "Regional services and Identity Domain discovery region."
}

variable "auth" {
  type        = string
  default     = "APIKey"
  description = "OCI provider authentication mode. Credentials stay outside this project."
  validation {
    condition     = contains(["APIKey", "SecurityToken", "InstancePrincipal", "ResourcePrincipal"], var.auth)
    error_message = "Use APIKey, SecurityToken, InstancePrincipal, or ResourcePrincipal."
  }
}

variable "config_file_profile" {
  type    = string
  default = "DEFAULT"
}

variable "compartment_ids" {
  type        = set(string)
  default     = []
  description = "Exact compartment IDs to scan for regional resources; empty means root plus all active compartments. Does not expand descendants. Policy collection remains tenancy-wide."
}

variable "services" {
  type        = set(string)
  default     = ["adb", "oic", "buckets"]
  description = "Regional services to read."
  validation {
    condition     = length(setsubtract(var.services, toset(["adb", "oic", "buckets"]))) == 0
    error_message = "Supported services: adb, oic, buckets."
  }
}

variable "include_identity_domains" {
  type        = bool
  default     = true
  description = "Discover domains and list their groups using SCIM. Requires read access in those domains."
}

variable "domain_ids" {
  type        = set(string)
  default     = []
  description = "Only read groups in these domain OCIDs; empty selects all active domains visible in this region."
}

variable "user_queries" {
  type        = map(set(string))
  default     = {}
  description = "Domain OCID => exact userNames whose direct group memberships should be collected."
}

variable "bucket_details" {
  type        = bool
  default     = true
  description = "Get each bucket to retrieve public access, versioning, encryption and size metadata."
}
