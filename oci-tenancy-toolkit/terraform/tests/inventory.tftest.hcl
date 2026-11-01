# terraform test uses mock providers: no OCI credentials or network API calls.
# Terraform >= 1.7 is required for these tests.
mock_provider "oci" {}
mock_provider "oci" { alias = "home" }

variables {
  tenancy_ocid    = "ocid1.tenancy.oc1..test"
  home_region     = "ca-toronto-1"
  region          = "ca-toronto-1"
  compartment_ids = ["ocid1.tenancy.oc1..test"]
  user_queries    = { "ocid1.domain.oc1..test" = ["alice@example.com"] }
}

override_data {
  target = module.tenancy.data.oci_identity_tenancy.this
  values = { name = "TestTenancy" }
}

override_data {
  target = module.tenancy.data.oci_identity_region_subscriptions.this
  values = {
    region_subscriptions = [{ region_name = "ca-toronto-1", is_home_region = true, state = "READY", region_key = "YYZ" }]
  }
}

override_data {
  target = module.tenancy.data.oci_identity_compartments.all
  values = {
    compartments = [{ id = "ocid1.compartment.oc1..child", name = "Production", compartment_id = "ocid1.tenancy.oc1..test", state = "ACTIVE", description = "Test" }]
  }
}

override_data {
  target = module.tenancy.data.oci_identity_policies.all["ocid1.tenancy.oc1..test"]
  values = {
    policies = [{ id = "ocid1.policy.oc1..test", name = "ReadOnly", compartment_id = "ocid1.tenancy.oc1..test", description = "Test", statements = ["Allow group Default/Operators to read buckets in tenancy"] }]
  }
}

override_data {
  target = module.tenancy.data.oci_identity_policies.all["ocid1.compartment.oc1..child"]
  values = { policies = [] }
}

override_data {
  target = module.regional.data.oci_identity_domains.all["ocid1.tenancy.oc1..test"]
  values = {
    domains = [{ id = "ocid1.domain.oc1..test", display_name = "Default", url = "https://example.identity.oraclecloud.com", home_region = "ca-toronto-1", compartment_id = "ocid1.tenancy.oc1..test", state = "ACTIVE" }]
  }
}

override_data {
  target = module.regional.data.oci_identity_domains.all["ocid1.compartment.oc1..child"]
  values = { domains = [] }
}

override_data {
  target = module.identity_domain["ocid1.domain.oc1..test"].data.oci_identity_domains_groups.all
  values = { groups = [{ id = "g1", ocid = "ocid1.group.oc1..test", display_name = "Operators" }] }
}

override_data {
  target = module.identity_domain["ocid1.domain.oc1..test"].data.oci_identity_domains_users.selected[0]
  values = { users = [{ id = "u1", ocid = "ocid1.user.oc1..test", user_name = "alice@example.com", active = true }] }
}

override_data {
  target = module.identity_domain["ocid1.domain.oc1..test"].data.oci_identity_domains_groups.membership["u1"]
  values = { groups = [{ id = "g1", ocid = "ocid1.group.oc1..test", display_name = "Operators" }] }
}

override_data {
  target = module.regional.data.oci_database_autonomous_databases.all["ocid1.tenancy.oc1..test"]
  values = {
    autonomous_databases = [{ id = "ocid1.autonomousdatabase.oc1..test", display_name = "Warehouse", compartment_id = "ocid1.tenancy.oc1..test", state = "AVAILABLE", db_name = "WH", db_workload = "DW" }]
  }
}

override_data {
  target = module.regional.data.oci_integration_integration_instances.all["ocid1.tenancy.oc1..test"]
  values = {
    integration_instances = [{ id = "ocid1.integrationinstance.oc1..test", display_name = "Integration", compartment_id = "ocid1.tenancy.oc1..test", state = "ACTIVE" }]
  }
}

override_data {
  target = module.regional.data.oci_objectstorage_namespace.this[0]
  values = { namespace = "testnamespace" }
}

override_data {
  target = module.regional.data.oci_objectstorage_bucket_summaries.all["ocid1.tenancy.oc1..test"]
  values = {
    bucket_summaries = [{ name = "exports", namespace = "testnamespace", compartment_id = "ocid1.tenancy.oc1..test" }]
  }
}

override_data {
  target = module.regional.data.oci_objectstorage_bucket.details["exports"]
  values = { access_type = "NoPublicAccess", versioning = "Enabled", approximate_count = 4, approximate_size = 2048 }
}

run "inventory_has_expected_relationships" {
  command = plan
  assert {
    condition     = length(output.inventory.compartments) == 2 && length(output.inventory.policies) == 1
    error_message = "Root and child compartments, and root policies must be included."
  }
  assert {
    condition     = length(output.inventory.resources) == 3
    error_message = "ADB, OIC, and bucket must be in the normalized inventory."
  }
  assert {
    condition     = output.inventory.memberships[0].user_id == "u1" && output.inventory.groups[0].domain_name == "Default"
    error_message = "Identity Domain membership IDs or group qualification were lost."
  }
  assert {
    condition     = one([for r in output.inventory.resources : r.details.public_access_type if r.kind == "bucket"]) == "NoPublicAccess"
    error_message = "Bucket detail GET must populate access metadata."
  }
}

run "can_disable_services_and_identity" {
  command = plan
  variables {
    services                 = []
    include_identity_domains = false
    user_queries             = {}
  }
  assert {
    condition     = length(output.inventory.resources) == 0 && length(output.inventory.groups) == 0 && length(output.inventory.policies) == 1
    error_message = "Disabled collectors must not populate inventory, while policies remain available."
  }
}

run "can_skip_bucket_details" {
  command = plan
  variables { bucket_details = false }
  assert {
    condition     = one([for r in output.inventory.resources : r.details.public_access_type if r.kind == "bucket"]) == null
    error_message = "Skipped bucket details must be null, not a fabricated safe value."
  }
}

run "unknown_compartment_is_rejected" {
  command = plan
  variables {
    compartment_ids = ["ocid1.compartment.oc1..missing"]
    services        = []
  }
  expect_failures = [output.inventory]
}

run "wrong_home_region_is_rejected" {
  command = plan
  variables { home_region = "us-ashburn-1" }
  expect_failures = [output.inventory]
}
