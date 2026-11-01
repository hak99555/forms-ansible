# Investigation recipes

## A user cannot access a resource

1. Confirm the Identity Domain and the exact username. Run `live-user-groups` or collect that user with `user_queries`.
2. For each returned group, run `group-policies` using its domain-qualified name or group OCID. Review matching statements, broad-principal candidates and unparsed statements.
3. Compare the resource's compartment and region from `resources` with each statement's scope. A policy's attachment compartment and its target scope are different concepts; named compartment paths are relative to the policy attachment. Ancestor policies can affect descendant compartments. The report retains these fields but does not resolve effective access.
4. Examine conditions such as `request.region`, `request.operation`, `request.permission`, tags, network source and `target.bucket.name`. A group-name match alone is insufficient.
5. Check the service's API permission table for every permission required by the failed operation. Check cross-tenancy agreements, application roles, identity-domain roles and federated sign-in context separately. Use the failed request's timestamp, OCID, operation and `opc-request-id` when looking in OCI Audit or contacting support.

The toolkit does not read OCI Audit, database contents or OIC integration payloads. It helps narrow the identity, policy and resource context for those investigations.

## Terraform returns 401/403/404

Check the selected profile, authentication mode, security-token expiry, API signing key/fingerprint, tenancy OCID and system clock. Confirm `home_region` is the actual tenancy home region and `region` is a subscribed region.

`NotAuthorizedOrNotFound` does not distinguish lack of permission from a nonexistent/wrong-region resource. Check domain URL, service region and compartment independently. Domain discovery and SCIM group/user access have separate authorization requirements. Use `domain_ids` to limit SCIM reads to domains you are authorized to inspect.

Collection stops on API failures. Do not export an old state after a failed collection and call it a fresh scan. The `collect` command writes the report only after plan, apply and export succeed; inspect its exit code and the report timestamp.

## Resources or domains appear to be missing

Run `summary` and inspect regions, services and exact compartment IDs. The root compartment is included by default. A compartment selection does not recursively include children. `resources --descendants` filters an existing snapshot; it cannot retrieve uncollected resources.

Collect every relevant READY subscribed region. Domain discovery returns domains homed or replicated in the queried region. Deleted/inactive compartments and their policies are outside the scan. Some list APIs may return only records visible to the caller. OIC inventory contains OCI-managed integration instances, not the integrations/connections inside them. ADB inventory contains Autonomous Database instances, not schemas or SQL grants.

## Duplicate group names

Use `Workforce/Operators` or the group OCID. `Operators` is rejected when ambiguous. An unqualified group subject in an OCI policy refers to the default domain; it must not be attributed to a same-named group in another domain. The analyzer matches policy subject tokens, not arbitrary substrings or group names appearing in conditions.

## ADB connectivity

Review state, lifecycle details, private endpoint, subnet, NSGs, IP ACL fields and mTLS requirements in the ADB resource details. Endpoint metadata is only a starting point: routes, DNS, security rules, wallets and database accounts must be checked separately. The toolkit does not download wallets or connect to the database.

## OIC failures

Review lifecycle state/details, instance URL, type and network endpoint metadata. OCI IAM controls instance administration; access inside OIC also uses application roles. A failed integration execution can occur while the OCI instance is ACTIVE. Use OIC monitoring and work-request diagnostics for execution/provisioning details; those APIs are outside this initial project.

## Buckets

Review public access, versioning and storage tier. Public-read findings are configuration-review prompts; some public buckets are intentional. A null `kms_key_id` means there is no customer-managed key recorded, not that the bucket is unencrypted. A private bucket can still be accessed through authorized identities or pre-authenticated requests; this toolkit does not enumerate PARs. Size/count statistics are approximate and may lag.

## Slow scans / throttling

The cost grows with compartments, regions, domains, selected users and buckets. Keep `user_queries` targeted, disable unneeded services, limit exact resource compartment IDs, or skip bucket details. Terraform uses the provider's retry behavior; SDK live lookups enable the default OCI retry strategy. If throttling persists, run the manual Terraform plan with `-parallelism=2` and retry after the service's retry window. Avoid concurrent runs in the same working directory.

## Policy changes and snapshot differences

`diff` compares observations, not a transaction log. Use matching collection coverage and a consistent time window. `merge` rejects different versions of the same global record; recollect rather than silently choosing a winner. A name-based policy can change meaning after a rename or compartment move; review the original statement and policy attachment. Unsupported policy syntax remains visible for manual investigation.

## Empty groups or users

`user_queries` defaults to empty, so a normal snapshot does not enumerate all users. An uncollected user lookup fails with an explanation. An empty direct-membership result is distinct from a missing user. Implicit All Domain Users membership and application roles are outside the membership result. Group lists omit member arrays to avoid nested-array response limits; live lookups paginate top-level groups filtered by the user's SCIM ID.
