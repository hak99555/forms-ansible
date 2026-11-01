# Collecting from the local page

Use the browser's **Collect snapshot** button with the toolkit's local helper. A plain `python -m http.server` or a file opened directly can browse inventory but cannot collect it.

From the toolkit directory, first install the optional SDK:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[live]"
.venv/Scripts/python -m oci_admin.web_server
```

On Linux/macOS use `.venv/bin/python`. Open exactly `http://127.0.0.1:8765/`, then **Collect snapshot**. An optional `--port` changes the local port. The helper cannot bind to other interfaces; do not put it behind a reverse proxy or expose it over a network.

OCI API-key authentication needs a private PEM signing key, its fingerprint, the tenancy OCID and the user OCID. Enter the private key in the masked PEM field, and its passphrase if encrypted. Enter the tenancy home region and one or more comma-separated scan regions. The corresponding public key must already be registered for that OCI user. See Oracle's [required keys and OCIDs](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/apisigningkey.htm) and [in-memory signer API](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/signing.html).

Choose ADB, OIC and/or buckets. The collector reads the root and all active compartments across those regions. Optional policies and domain groups require additional permissions; user memberships are not queried in this flow. The [reader permissions guide](permissions.md) also applies to this SDK path. Any API error stops the collection; it does not replace the existing snapshot with incomplete data.

When collection finishes, the new snapshot appears automatically. `collection_started_at` records when the scan began; `collected_at` records completion in UTC and is displayed in local time. Use **Save snapshot** to download the inventory for later use with the page or Python utilities. It includes metadata and scope, not the credentials supplied to authenticate. Nothing is downloaded automatically.

## Credential lifecycle

1. The page accepts credentials only when served by this helper on `127.0.0.1`. It makes no external browser requests for collection.
2. At submission, credential fields immediately clear. The JSON request is sent only to the same loopback origin, using a session-specific CSRF header. Credentials do not enter URLs, cookies, local/session storage, IndexedDB or a service worker.
3. The helper validates the Host, Origin, content type, request size and CSRF token. It has no CORS allowances. Static assets and API responses use `Cache-Control: no-store`; frame embedding and third-party scripts are blocked by CSP.
4. The JSON body is passed through a pipe to a fresh Python process. That process constructs Oracle's signer using `private_key_content`; it does not read or create an OCI config file or temporary key file. The private key itself is not sent to OCI; the SDK uses it to sign requests.
5. Only snapshot data or a fixed error response leaves the worker. SDK exception text, stderr and access logs are suppressed to avoid credential leakage. The app never places credentials in subprocess arguments, environment variables, Terraform inputs/state or reports.
6. The worker closes its client sessions and exits after success or failure. A collection exceeding 10 minutes is terminated by the helper. The next attempt asks for credentials again. Disconnecting or closing the tab does not immediately cancel the worker; it may continue until completion or the timeout.

The application deliberately avoids credential persistence. That is not a guarantee of forensic erasure from browser/process memory, swap, crash dumps, clipboard managers, password managers or extensions. Use a trusted machine, browser and narrowly scoped reader identity. Browser password managers may ignore autocomplete hints; decline any save prompt. The key remains an active OCI credential until revoked in OCI; the application does not revoke it.

Only one collection runs at a time. The helper's origin checks protect against browser cross-site requests and DNS rebinding; they do not isolate mutually untrusted programs running under the same OS account. Stop the helper with Ctrl+C when finished. This is a local development utility, not a multi-user credential service.

## Verification

```powershell
python -m unittest discover -s tests -v
node --test web/tests/core.test.cjs
```

Endpoint tests use fake credentials and mock SDK responses. They verify origin/Host/CSRF rejection, no-cache responses, no credential echo, stdin-only worker transfer, timeout termination, and snapshot normalization. Real tenancy permissions and connectivity must be verified with your own reader identity; no live tenancy credentials were used in development.
