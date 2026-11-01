# OCI Tenancy Toolkit

A Terraform project and command-line utilities for OCI tenancy administration, with **Identity Domains**, **Autonomous Database (ADB)**, **Oracle Integration (OIC)** and **Object Storage buckets**.

Terraform collects inventory using data sources. Python turns snapshots into useful reports, matches group references in policy statements, checks configuration, and compares observations. Optional OCI SDK support provides a current user-membership lookup without refreshing the entire inventory.

## What you can do

**Browser interface:** open [web/dist/index.html](web/dist/index.html), then choose **Open snapshot** to browse the compartment tree, see resource totals across descendants, and search by OCID, type, name pattern, region or state. It works locally without a server and processes imported data in the browser. See [web/README.md](web/README.md).

**Collect from the page:** start the local helper with `python -m oci_admin.web_server` using an environment with the optional `[live]` dependency installed. Open its `http://127.0.0.1:8765/` URL and choose **Collect snapshot**. It asks for the tenancy/user OCIDs, fingerprint, PEM private key and optional passphrase. Credentials are passed in memory to a one-shot OCI SDK process and are not saved by the application. This path creates no Terraform state. See [local collection and credential handling](docs/local-collection.md).

| Task | Command |
| --- | --- |
| List Identity Domain groups | `groups` |
| Find statements naming a group, including group OCIDs | `group-policies` |
| Check a selected user's direct group memberships | `user-groups` or `live-user-groups` |
| Display compartments and their resources | `tree` |
| List ADB, OIC or buckets by region/compartment | `resources` |
| Review all policies and their attachment paths | `policies` |
| Inspect domains and inventory coverage | `domains`, `summary` |
| Flag public buckets, unhealthy resources, broad admin statements, missing tags | `checks` |
| Combine regions or compare snapshots | `merge`, `diff` |
| Refresh a data-only Terraform snapshot | `collect` |

## Project structure

```text
oci-tenancy-toolkit/
  terraform/
    main.tf                  # Composition and normalized inventory output
    providers.tf             # Regional provider + tenancy home-region provider
    variables.tf             # Scope, services, domains, selected users
    versions.tf              # Provider version and local backend
    .terraform.lock.hcl       # Verified provider dependency hashes
    terraform.tfvars.example
    modules/
      tenancy/               # Tenancy, regions, compartment hierarchy, policies
      regional/              # ADB, OIC, buckets, domain discovery
      identity-domain/       # SCIM groups and selected user memberships
    tests/                   # Terraform tests using mock providers
  oci_admin/                 # Python CLI, reports, policy parser, optional SDK
  examples/demo.snapshot.json
  docs/permissions.md
  docs/troubleshooting.md
  docs/design.md
  tests/                     # Python unit and CLI tests
  pyproject.toml
```

## Try it immediately, without OCI credentials

Use Python 3.10+ from the project directory. Offline reporting has no third-party dependencies.

```powershell
python -m oci_admin summary examples/demo.snapshot.json
python -m oci_admin tree examples/demo.snapshot.json
python -m oci_admin groups examples/demo.snapshot.json
python -m oci_admin group-policies examples/demo.snapshot.json "Workforce/OCI-Operators"
python -m oci_admin user-groups examples/demo.snapshot.json "alice@example.com"
python -m oci_admin checks examples/demo.snapshot.json --required-tag Owner
```

The sample contains fictitious OCIDs and deliberately includes a public bucket and a failed OIC instance to demonstrate findings.

## Connect to your tenancy

1. Install Terraform 1.6+ (1.7+ for mock tests) and Python 3.10+. This project was verified with Terraform 1.17.1 and Oracle OCI provider 9.11.0; the provider version is constrained and locked.
2. Configure an OCI profile in your usual `~/.oci/config`. Use your approved credentials and a reader identity with the permissions described in [permissions.md](docs/permissions.md). API keys and private keys stay outside this project. The OCI CLI's `oci setup config` can help create a profile if the CLI is installed.
3. Copy the example variables and enter your tenancy OCID, tenancy home region, scan region and profile. Optionally restrict domain OCIDs, services or compartments.

Windows PowerShell:

```powershell
Copy-Item terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit terraform/terraform.tfvars before continuing.
terraform -chdir=terraform init
terraform -chdir=terraform validate
python -m oci_admin collect --out reports/toronto.json
```

Linux/macOS use `cp terraform/terraform.tfvars.example terraform/terraform.tfvars`; the remaining commands are identical.

`collect` runs a plan, inspects its JSON, rejects any managed resource (including a managed resource with no changes), applies that saved data-only plan to local state, and exports the inventory. It does **not** provision, update or delete OCI resources. It performs real API reads, which can appear in OCI Audit. It requires an initialized Terraform directory and uses the currently selected workspace.

To review the plan yourself:

```powershell
terraform -chdir=terraform plan -out=inventory.tfplan
terraform -chdir=terraform apply inventory.tfplan
python -m oci_admin export --out reports/toronto.json
```

Only use the manual workflow with this project's data-only configuration. Do not mix it with infrastructure provisioning code.

`export` reads the last saved output; it does not refresh anything. A successful collection is necessary before exporting a current report. Failed collections return nonzero and do not write a replacement report; an older report with the same filename may still exist, so check `collected_at`.

## Common reports

```powershell
# Groups; qualify names because multiple domains can contain the same group name.
python -m oci_admin groups reports/toronto.json --domain Workforce --format csv --out reports/groups.csv

# Statement, policy name, attachment path, verb, resource type, scope, conditions.
python -m oci_admin group-policies reports/toronto.json "Workforce/OCI-Operators" --out reports/operator-policies.json
# The query also accepts an actual group OCID or SCIM ID from the groups report.

python -m oci_admin tree reports/toronto.json --out reports/tree.txt
python -m oci_admin compartments reports/toronto.json --format csv --out reports/compartments.csv
python -m oci_admin resources reports/toronto.json --kind adb
python -m oci_admin resources reports/toronto.json --kind oic
python -m oci_admin resources reports/toronto.json --kind bucket --format csv --out reports/buckets.csv
python -m oci_admin resources reports/toronto.json --compartment Production --descendants
python -m oci_admin checks reports/toronto.json --required-tag Owner --required-tag Operations.CostCenter
python -m oci_admin checks reports/toronto.json --fail-on-warning --out reports/findings.json
```

JSON is the default and preserves nested data. CSV is available for list reports; nested values are JSON cells, and potentially executable spreadsheet formulas are escaped. Group-policy and membership reports are nested JSON so their interpretation notes remain attached.

Exit codes: `0` success, `1` command/query error, `2` findings with severity `warning` when `checks --fail-on-warning` is used. No findings means only that these limited checks found nothing in the collected scope.

## User memberships in Identity Domains

First list domain OCIDs with `domains`. Add selected users to your variables and collect again:

```hcl
user_queries = {
  "ocid1.domain.oc1..YOUR_DOMAIN" = ["alice@example.com", "bob@example.com"]
}
```

```powershell
python -m oci_admin collect --out reports/toronto.json
python -m oci_admin user-groups reports/toronto.json "Workforce/alice@example.com"
```

The `userName` must match the Identity Domain username; it is not necessarily the user's email address. A requested user who is not returned causes collection to fail rather than presenting an empty membership list.

For a live lookup, install the optional SDK in a virtual environment:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[live]"
.venv/Scripts/python -m oci_admin live-user-groups "alice@example.com" --domain-url "https://idcs-YOUR_DOMAIN.identity.oraclecloud.com" --profile DEFAULT
```

On Linux/macOS, use `.venv/bin/python`. `--by id` accepts a SCIM user ID; `--by ocid` accepts a user OCID. The domain URL must be the base URL shown in OCI, without `/admin/v1`. API-key, security-token, instance-principal and resource-principal authentication modes are exposed; whether a principal can access a domain depends on your tenancy's IAM/domain configuration.

Both membership utilities query groups using `members.value` with the resolved SCIM user ID, and paginate the results. They report **direct memberships**. Implicit All Domain Users membership, indirect/dynamic entitlements and application roles are not evaluated. These reports are not a complete application-authorization analysis.

## Multiple regions

Compartments and policies are global; ADB, OIC and buckets are regional. Identity Domains can be homed outside the tenancy home region, so domain discovery runs in the scan region. A domain without a home or replica there will not be discovered in that run.

Collect each relevant subscribed region in its own Terraform workspace, then merge. Use `workspace new` the first time and `workspace select` afterward. Do not run simultaneous collections in the same Terraform working directory.

```powershell
terraform -chdir=terraform workspace new toronto
python -m oci_admin collect --region ca-toronto-1 --out reports/toronto.json
terraform -chdir=terraform workspace new montreal
python -m oci_admin collect --region ca-montreal-1 --out reports/montreal.json
python -m oci_admin merge reports/toronto.json reports/montreal.json --out reports/tenancy.json
python -m oci_admin summary reports/tenancy.json
```

The region names above are examples: use your actual subscriptions. If `domain_ids` or `user_queries` select a domain that is absent from a particular region, use separate variable files for each region with `collect --var-file path/to/region.tfvars`. `domain_ids=[]` discovers available active domains; `user_queries={}` skips user lookup. `home_region` remains the tenancy's home region in every scan.

`merge` preserves each scan's region/service/compartment scope and refuses conflicting duplicate observations. If global metadata changed between scans, recollect consistent snapshots. A merge is not an atomic tenancy snapshot.

## Compare observations

```powershell
python -m oci_admin diff reports/before.json reports/after.json --out reports/changes.json
```

The comparison covers resources, policies, domains, groups, selected users, memberships, compartments and region subscriptions. List order and timestamps are ignored. Different coverage is rejected unless `--allow-scope-change` is explicitly supplied; otherwise an omitted compartment might look like deleted resources. Differences do not replace OCI Audit history.

## Policy report boundaries

The policy analyzer matches local `Allow` subjects using domain-qualified names, default-domain names or group OCIDs. It preserves conditions, raw statements and the compartment where the policy is attached. `any-user` and `any-group` statements are separate candidates; unsupported statements, including cross-tenancy `Define`/`Endorse`/`Admit` statements, are shown for manual review.

This is an inventory of **declared policy candidates**, not an effective-access simulator. It does not evaluate conditions, expand every resource family into API permissions, resolve compartment inheritance, combine cross-tenancy agreements, evaluate deny/system policies, or inspect OIC application roles/database SQL privileges. Oracle's [policy syntax](https://docs.oracle.com/en-us/iaas/Content/Identity/Concepts/policysyntax.htm) explains subjects, scope and conditions; use the relevant service permission reference when investigating a specific operation.

## State and scope

The configuration contains only data sources and outputs. The local backend keeps inventory metadata, policy text, usernames, endpoints and tags in state. `sensitive=true` hides the output in normal Terraform display; it does not encrypt state or JSON exports. Protect state/reports as administrative data. `.gitignore` excludes credentials, tfvars, state, plans and reports while retaining the provider lock file.

`compartment_ids` selects **exact IDs**, not descendants, and limits regional resource scans. Policies are still read at the root and all active compartments to preserve policy visibility. `services=[]` skips all regional resources; `include_identity_domains=false` skips domain discovery and SCIM reads. `bucket_details=false` skips per-bucket detail calls and marks those checks as unavailable.

API failures stop Terraform collection. An empty result is an observation under the caller's permissions, not independent proof that a compartment or domain is empty. Review `summary` coverage before drawing tenancy-wide conclusions.

## Verify and extend

```powershell
python -m unittest discover -s tests -v
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
terraform -chdir=terraform test
```

The Terraform tests use mock providers and need no OCI credentials. They require provider installation via `terraform init`. Live tenancy access was not used to develop this scaffold.

See [design.md](docs/design.md) for the snapshot contract and extension points, [permissions.md](docs/permissions.md) for reader-policy examples, and [troubleshooting.md](docs/troubleshooting.md) for operational investigations.
