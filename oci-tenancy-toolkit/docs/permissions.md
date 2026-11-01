# Reader permissions

Use a dedicated group in an Identity Domain. The following is a starting policy for the API-key user running the toolkit; replace `Default` and `OCI-Tenancy-Readers` with your domain/group names. An authorized tenancy administrator can review and create it at the tenancy root. This toolkit does not create policies or assign roles.

```text
Allow group 'Default'/'OCI-Tenancy-Readers' to inspect tenancies in tenancy
Allow group 'Default'/'OCI-Tenancy-Readers' to inspect compartments in tenancy
Allow group 'Default'/'OCI-Tenancy-Readers' to read policies in tenancy
Allow group 'Default'/'OCI-Tenancy-Readers' to inspect domains in tenancy
Allow group 'Default'/'OCI-Tenancy-Readers' to inspect groups in tenancy
Allow group 'Default'/'OCI-Tenancy-Readers' to inspect users in tenancy
Allow group 'Default'/'OCI-Tenancy-Readers' to inspect autonomous-databases in tenancy
Allow group 'Default'/'OCI-Tenancy-Readers' to inspect integration-instance in tenancy
Allow group 'Default'/'OCI-Tenancy-Readers' to read buckets in tenancy
Allow group 'Default'/'OCI-Tenancy-Readers' to read objectstorage-namespaces in tenancy
```

These statements cover the infrastructure API operations used: tenancy/subscription/compartment/domain discovery, policy listing, regional ADB/OIC lists and bucket metadata. Read access to bucket contents is not needed. `inspect buckets` is enough for listing if `bucket_details=false`; detail GETs require `read buckets`. Listing policies requires `read policies`. Oracle documents these mappings in the [IAM service reference](https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/iampolicyreference.htm), [Object Storage service reference](https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/objectstoragepolicyreference.htm), and [OIC policy reference](https://docs.oracle.com/en/cloud/paas/application-integration/oracle-integration-oci/iam-policies-oracle-integration.html).

Identity Domains `/admin/v1/Users` and `/admin/v1/Groups` also enforce domain authorization. Domain discovery permission alone does not establish permission to read users/groups in every domain. Confirm the calling identity can perform the required searches in each selected domain; approved domain administrator-role assignments and IAM policy scope both matter. Do not grant `manage all-resources` merely to make this report work. The toolkit uses OCI request signatures rather than a browser login; see [Identity Domains API authorization](https://docs.oracle.com/en-us/iaas/Content/Identity/api-getstarted/api-managing-authorization.htm).

If your account only has access to selected domains, set `domain_ids` to those domain OCIDs. If you cannot use SCIM yet, set `include_identity_domains=false` and `user_queries={}` to collect regional resources and policies independently. A successful SCIM response can still be visibility-filtered by the service; validate expected groups with the domain administrator before treating it as exhaustive.

For restricted regional inventory, replace the last service statements' tenancy scope with approved compartments and set `compartment_ids` to precisely those IDs. This project still reads policies across all active compartments. A reader without that visibility must obtain the required policy-read scope or adapt the tenancy module and clearly label the resulting policy report as partial.

The `auth` Terraform variable supports `APIKey`, `SecurityToken`, `InstancePrincipal`, and `ResourcePrincipal`. The optional Python command uses the corresponding kebab-case `--auth` values. For principals other than users, IAM subjects and domain access need configuration appropriate to that principal. No credentials are embedded in the example variables.
