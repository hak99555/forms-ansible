"""Optional GET-only Identity Domains queries. No SDK dependency for offline use."""

import json
from pathlib import Path
from urllib.parse import urlsplit


def scim_pages(method, **kwargs):
    """SCIM uses 1-based offsets, not OCI opc-next-page tokens."""
    start, seen, rows, expected_total = 1, set(), [], None
    while True:
        data = method(start_index=start, count=1000, **kwargs).data
        batch = data.resources or []
        total = data.total_results
        if total is None or total < 0:
            raise ValueError("SCIM response omitted a valid totalResults; completeness cannot be established")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise ValueError("SCIM collection changed during pagination; retry the query")
        if data.start_index is not None and data.start_index != start:
            raise ValueError("SCIM returned an unexpected startIndex")
        if not batch:
            if len(rows) != total:
                raise ValueError("SCIM returned an empty page before totalResults was reached")
            break
        for row in batch:
            if not row.id or row.id in seen:
                raise ValueError("SCIM returned a missing/duplicate ID; retry the query")
            seen.add(row.id)
            rows.append(row)
        if len(rows) == total:
            break
        if len(rows) > total:
            raise ValueError("SCIM returned more records than totalResults; retry the query")
        start += len(batch)
    return rows


def domain_client(endpoint, config_file, profile, auth):
    try:
        import oci
    except ImportError as error:
        raise ValueError('Live queries require: python -m pip install -e ".[live]"') from error
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ValueError("Use the HTTPS domain base URL from OCI (without /admin/v1 or credentials)")
    options = {"retry_strategy": oci.retry.DEFAULT_RETRY_STRATEGY, "timeout": (10, 60)}
    if auth == "instance-principal":
        config = {}
        options["signer"] = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    elif auth == "resource-principal":
        config = {}
        options["signer"] = oci.auth.signers.get_resource_principals_signer()
    else:
        config = oci.config.from_file(str(Path(config_file).expanduser()), profile)
        if auth == "security-token":
            token = Path(config["security_token_file"]).expanduser().read_text().strip()
            key = oci.signer.load_private_key_from_file(str(Path(config["key_file"]).expanduser()), config.get("pass_phrase"))
            options["signer"] = oci.auth.signers.SecurityTokenSigner(token, key)
    return oci.identity_domains.IdentityDomainsClient(config, service_endpoint=endpoint.rstrip("/"), **options)


def live_user_groups(client, user_query, by="name"):
    attribute = {"name": "userName", "id": "id", "ocid": "ocid"}[by]
    users = scim_pages(client.list_users, filter=f"{attribute} eq {json.dumps(user_query)}", attributes="id,ocid,userName,active")
    if len(users) != 1:
        raise ValueError(f"Expected one user; found {len(users)}")
    user = users[0]
    groups = scim_pages(client.list_groups, filter=f"members.value eq {json.dumps(user.id)}", attributes="id,ocid,displayName")
    return {
        "user": {"id": user.id, "ocid": user.ocid, "name": user.user_name, "active": user.active},
        "groups": [{"id": g.id, "ocid": g.ocid, "name": g.display_name} for g in groups],
        "membership_semantics": "direct-scim-members-filter",
        "note": "Implicit All Domain Users membership, application roles and indirect entitlements are not evaluated.",
    }
