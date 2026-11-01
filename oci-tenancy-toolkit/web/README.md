# OCI Tenancy Explorer

Open `dist/index.html` directly in a modern browser. It works offline without a build, server or installed packages. Click **Open snapshot**, or drop a JSON file anywhere on the page. Use the toolkit's `collect`, `export` or `merge` output. The initial demo is fictitious.

Each tree node shows resources directly in that compartment plus resources in every descendant. Hover a node to see the direct, child-only and total counts. With filters active, badges show **matching / total** for each subtree. Counts refer to inventoried resources, including buckets themselves, rather than the objects inside buckets or IAM users/groups/policies.

Select a compartment to scope the table. **Include descendants** controls whether child compartments are included. **Entire snapshot** searches all imported compartments. Expand and collapse controls change tree visibility without changing search scope.

Filters combine with AND: OCID contains or exact match, resource type, region, state and name pattern. Names are case-insensitive: ordinary text matches a substring, while patterns containing `*` or `?` match the whole name. `*` matches any number of characters and `?` matches one. Regular expressions are not executed. Open a result for its OCID, compartment, metadata and a **Show compartment** action. Results are sortable and paginated; JSON export includes every matching resource, not just the visible page.

Imported files are processed in the browser tab and never sent to a server or saved to browser storage. Closing/reloading the page clears the imported file. Actual tenancy metadata is not included in the site source. Native Terraform output and `terraform output -json` wrappers are accepted, including UTF-8/UTF-16 exports. Invalid snapshots leave the current view in place; files above 100 MB are rejected.

**Collect snapshot** requires the local helper, started from the toolkit directory with `python -m oci_admin.web_server` in a Python environment with the optional OCI SDK installed. The dialog asks for signing credentials, clears them on submission, and uses a one-shot backend process without saving an OCI profile, private key or Terraform state. Only same-origin loopback requests are accepted. See [the credential lifecycle and setup guide](../docs/local-collection.md). The browser cannot guarantee OS-level memory erasure. **Save snapshot** explicitly downloads inventory without the supplied credentials.

The page displays observed snapshot data, not a live OCI query. Refresh with `python -m oci_admin collect --out reports/latest.json`, then reopen that file. A merged snapshot can have different service/compartment coverage in each region. An absent resource does not prove it does not exist in the tenancy.

Optional local HTTP preview from the toolkit directory:

```powershell
python -m http.server 8765 --bind 127.0.0.1 --directory web/dist
```

Visit `http://127.0.0.1:8765`. To verify the query/counting logic, use Node 18+:

```powershell
node --test web/tests/core.test.cjs
```
