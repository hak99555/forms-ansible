# Design and extension points

## Why Terraform plus Python

Terraform data sources give reproducible, parameterized collection using the OCI provider. HCL handles discovery and relationships well, while policy-language parsing, recursive reports and snapshot comparison are easier to maintain in Python. Offline reports use only Python's standard library. The optional OCI SDK is loaded only by `live-user-groups`.

There are no managed Terraform resources, imports, provisioners or external-data scripts in this project. The collector inspects a saved plan before applying it and rejects managed infrastructure or deferred changes. Terraform data-source reads can occur during planning, so the guard is intended for this trusted configuration, not as a sandbox for arbitrary third-party Terraform code.

## Collection boundaries

The `tenancy` module uses the home-region provider, adds the root compartment explicitly, and obtains all active descendants with `compartment_id_in_subtree=true` and `access_level=ANY`. It reads policies in the root and every returned active compartment. A successful list is still subject to service behavior and reader visibility; `ANY` is not permission to read arbitrary resources.

The `regional` module uses one explicit scan-region provider. Terraform provider aliases cannot be generated dynamically with `for_each`; separate workspaces and reports make the region/state relationship explicit. Domain discovery uses each scan region because Identity Domains can have other home/replica regions.

The `identity-domain` module reads SCIM groups using `id,ocid,displayName` and selected users using `id,ocid,userName,active`. Membership queries filter the paginated groups collection with `members.value`. This avoids requesting a group's entire nested member array, which has independent limits. The installed 9.11.0 provider's group/user list pagination is implemented by Oracle; the Python SDK helper implements SCIM offset pagination explicitly and fails on duplicate IDs, changing totals or truncated responses.

The Terraform provider schema uses `display_name` for a domain and `state` for a region subscription, even where prose documentation calls them name/status. These are normalized to `name` and `status` in the snapshot contract and exercised by mock-provider tests.

## Snapshot contract (schema version 1)

| Field | Meaning |
| --- | --- |
| `schema_version`, `collected_at` | Format version and observation/export timestamp |
| `tenancy` | Tenancy ID/name |
| `regions` | Subscriptions with `region_name`, `is_home_region`, `status` |
| `compartments` | ID/name, parent `compartment_id`, state, description; root has a null parent |
| `policies` | ID/name, attachment `compartment_id`, description, original statements |
| `domains` | Domain OCID/name, base URL, home region, compartment, state |
| `groups` | SCIM ID, OCI OCID, name, domain OCID/name |
| `users` | Selected users only: SCIM ID, OCI OCID, username, active flag, domain |
| `memberships` | Domain ID, user SCIM ID, group SCIM ID, direct membership type |
| `resources` | Kind, stable ID, name, region, compartment, state, tags, service details |
| `coverage` | Scanned regions/services/compartments/domains, selected users, toggles and membership semantics |

Buckets use `region/namespace/name` as a stable reporting ID. A bucket rename or recreation can therefore appear as changes to observed metadata rather than a globally unique lifecycle identity. Keep this distinction in mind when using snapshots as operational evidence.

Merged snapshots retain the original per-scan coverage in `coverage.scans` and original timestamps in `source_timestamps`. Their top-level `collected_at` is the merge time. A union of regions is not a claim that every service and compartment was scanned in every region. Comparisons require matching coverage unless the caller explicitly opts into a partial comparison.

## Adding a service

1. Add its name to the root `services` validation/default if desired.
2. Add a regional data source keyed by exact compartment IDs, under a service-selection condition.
3. Normalize records to the resource contract and put service-specific fields in `details`.
4. Add a CLI kind choice, applicable configuration checks, mock-provider fixtures, permission documentation and coverage tests.

Useful future additions include VCN/subnet/NSG context, OIC work requests, ADB backup inventory, bucket retention/lifecycle policies, OCI Audit correlation, service limits/quotas and tag governance. They require their own API calls and permissions; none is silently represented as already collected.

## References

- [Oracle OCI Terraform provider](https://registry.terraform.io/providers/oracle/oci/latest/docs)
- [Provider 9.11.0 Identity Domains group pagination](https://github.com/oracle/terraform-provider-oci/blob/v9.11.0/internal/service/identity_domains/identity_domains_groups_data_source.go)
- [OCI Identity Domains Python client](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/identity_domains/client/oci.identity_domains.IdentityDomainsClient.html)
- [Compartment discovery data source](https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/latest/docs/d/identity_compartments.html)
- [IAM policy syntax](https://docs.oracle.com/en-us/iaas/Content/Identity/Concepts/policysyntax.htm)
- [Identity Domain group-member response limits](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/identity_domains/models/oci.identity_domains.models.GroupMembers.html)
