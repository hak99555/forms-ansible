"""One-shot SDK collector. Credentials enter on stdin; only inventory exits stdout.

Never reads OCI profiles, writes keys/state, or emits exception text/tracebacks.
The process exits after every collection, releasing signer and credential memory.
"""

import json
import re
import sys
from datetime import datetime, timezone


def validate_request(request):
    if not isinstance(request, dict):
        raise ValueError("Expected a collection request")
    for key, prefix in (("tenancy_ocid", "ocid1.tenancy."), ("user_ocid", "ocid1.user.")):
        if not isinstance(request.get(key), str) or not request[key].startswith(prefix):
            raise ValueError(f"Provide a valid {key}")
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){15}[0-9a-fA-F]{2}", request.get("fingerprint", "")):
        raise ValueError("Provide the API signing key fingerprint (16 colon-separated hex pairs)")
    key = request.get("private_key", "")
    if not isinstance(key, str) or not 50 < len(key) < 32768 or "PRIVATE KEY-----" not in key:
        raise ValueError("Provide a PEM private signing key")
    if not isinstance(request.get("passphrase", ""), str):
        raise ValueError("Invalid key passphrase")
    if not re.fullmatch(r"[a-z]{2,4}-[a-z0-9]+-\d+", request.get("home_region", "")):
        raise ValueError("Provide the tenancy home region, such as ca-toronto-1")
    regions = request.get("regions", [])
    if not isinstance(regions, list) or not regions or len(regions) > 100 or any(not isinstance(r, str) or not re.fullmatch(r"[a-z]{2,4}-[a-z0-9]+-\d+", r) for r in regions):
        raise ValueError("Choose one or more region identifiers")
    services = request.get("services", [])
    if not isinstance(services, list) or not services or any(s not in ("adb", "oic", "buckets") for s in services):
        raise ValueError("Choose supported services: adb, oic, buckets")
    for key in ("include_identity", "bucket_details"):
        if not isinstance(request.get(key), bool):
            raise ValueError(f"Invalid {key} option")
    return request


def collect(request, oci):
    """Only list/get SDK operations; no Terraform state or key file is needed."""
    from oci_admin.live import scim_pages

    request = validate_request(request)
    started = datetime.now(timezone.utc).isoformat()
    signer = oci.signer.Signer(
        tenancy=request["tenancy_ocid"], user=request["user_ocid"], fingerprint=request["fingerprint"],
        private_key_file_location=None, private_key_content=request.pop("private_key"),
        pass_phrase=request.pop("passphrase", "") or None,
    )
    options = {"signer": signer, "retry_strategy": oci.retry.DEFAULT_RETRY_STRATEGY, "timeout": (10, 45)}
    clients = []

    def client(cls, region, **kwargs):
        instance = cls({"region": region}, **options, **kwargs)
        clients.append(instance)
        return instance

    def listing(method, **kwargs):
        return oci.pagination.list_call_get_all_results(method, **kwargs).data

    def plain(value):
        return oci.util.to_dict(value)

    def fields(obj, names):
        return {name: plain(getattr(obj, name, None)) for name in names}

    tenancy_id = request["tenancy_ocid"]
    try:
        identity = client(oci.identity.IdentityClient, request["home_region"])
        tenancy = identity.get_tenancy(tenancy_id).data
        subscriptions = listing(identity.list_region_subscriptions, tenancy_id=tenancy_id)
        if request["home_region"] not in [r.region_name for r in subscriptions if r.is_home_region]:
            raise ValueError("Home region does not match the tenancy")
        ready = {r.region_name for r in subscriptions if r.status == "READY"}
        regions = sorted(set(request["regions"]))
        if not set(regions) <= ready:
            raise ValueError("Every selected region must be a READY tenancy subscription")
        compartments = [{"id": tenancy_id, "name": tenancy.name, "compartment_id": None, "state": "ACTIVE", "description": "Tenancy root"}]
        compartments += [dict(fields(c, ("id", "name", "compartment_id", "description")), state=c.lifecycle_state)
                         for c in listing(identity.list_compartments, compartment_id=tenancy_id,
                                          compartment_id_in_subtree=True, access_level="ANY", lifecycle_state="ACTIVE")]
        ids = [c["id"] for c in compartments]
        snapshot = {"schema_version": 1, "collection_started_at": started,
                    "tenancy": {"id": tenancy_id, "name": tenancy.name}, "compartments": compartments,
                    "regions": [fields(r, ("region_name", "region_key", "is_home_region", "status")) for r in subscriptions],
                    "policies": [], "domains": [], "groups": [], "users": [], "memberships": [], "resources": []}
        if request["include_identity"]:
            for cid in ids:
                snapshot["policies"] += [fields(p, ("id", "name", "compartment_id", "description", "statements"))
                                         for p in listing(identity.list_policies, compartment_id=cid, lifecycle_state="ACTIVE")]
        domain_ids = set()
        for region in regions:
            database = client(oci.database.DatabaseClient, region) if "adb" in request["services"] else None
            integration = client(oci.integration.IntegrationInstanceClient, region) if "oic" in request["services"] else None
            storage = client(oci.object_storage.ObjectStorageClient, region) if "buckets" in request["services"] else None
            namespace = storage.get_namespace(compartment_id=tenancy_id).data if storage else None
            regional_identity = client(oci.identity.IdentityClient, region) if request["include_identity"] else None
            for cid in ids:
                if database:
                    for r in listing(database.list_autonomous_databases, compartment_id=cid):
                        snapshot["resources"].append(dict(fields(r, ("id", "compartment_id", "freeform_tags", "defined_tags")),
                            kind="adb", name=r.display_name, region=region, state=r.lifecycle_state,
                            details=fields(r, ("db_name", "db_workload", "db_version", "compute_model", "compute_count", "cpu_core_count",
                                "data_storage_size_in_tbs", "is_auto_scaling_enabled", "is_dedicated", "is_free_tier", "is_mtls_connection_required",
                                "private_endpoint", "subnet_id", "nsg_ids", "whitelisted_ips", "is_access_control_enabled", "lifecycle_details"))))
                if integration:
                    for r in listing(integration.list_integration_instances, compartment_id=cid):
                        snapshot["resources"].append(dict(fields(r, ("id", "compartment_id", "freeform_tags", "defined_tags")),
                            kind="oic", name=r.display_name, region=region, state=r.lifecycle_state,
                            details=fields(r, ("integration_instance_type", "instance_url", "message_packs", "is_byol", "network_endpoint_details", "lifecycle_details"))))
                if storage:
                    for r in listing(storage.list_buckets, namespace_name=namespace, compartment_id=cid):
                        detail = {"namespace": namespace, "details_collected": request["bucket_details"]}
                        if request["bucket_details"]:
                            bucket = storage.get_bucket(namespace_name=namespace, bucket_name=r.name).data
                            detail.update(fields(bucket, ("versioning", "storage_tier", "kms_key_id", "approximate_count", "approximate_size", "object_events_enabled")))
                            detail["public_access_type"] = bucket.public_access_type
                        snapshot["resources"].append(dict(fields(r, ("name", "compartment_id", "freeform_tags", "defined_tags")),
                            kind="bucket", id=f"{region}/{namespace}/{r.name}", region=region, state=None, details=detail))
                if regional_identity:
                    for domain in listing(regional_identity.list_domains, compartment_id=cid):
                        if domain.id in domain_ids:
                            continue
                        domain_ids.add(domain.id)
                        snapshot["domains"].append(dict(fields(domain, ("id", "url", "home_region", "compartment_id")),
                                                        name=domain.display_name, state=domain.lifecycle_state))
                        if domain.lifecycle_state == "ACTIVE":
                            scim = client(oci.identity_domains.IdentityDomainsClient, region, service_endpoint=domain.url)
                            snapshot["groups"] += [{"id": g.id, "ocid": g.ocid, "name": g.display_name,
                                "domain_id": domain.id, "domain_name": domain.display_name}
                                for g in scim_pages(scim.list_groups, attributes="id,ocid,displayName")]
        snapshot["collected_at"] = datetime.now(timezone.utc).isoformat()
        snapshot["coverage"] = {"regions": regions, "services": sorted(set(request["services"])), "compartment_ids": sorted(ids),
            "domain_ids": sorted(domain_ids), "identity_domains": request["include_identity"], "bucket_details": request["bucket_details"],
            "user_queries": {}, "policies": "root-and-all-active-compartments" if request["include_identity"] else "not-collected",
            "membership_semantics": "not-collected", "incomplete": False, "collector": "ephemeral-oci-sdk"}
        return snapshot
    finally:
        for instance in clients:
            instance.base_client.session.close()
        request.clear()


def main():
    try:
        request = json.load(sys.stdin)
        validate_request(request)
        import oci
        result = collect(request, oci)
        json.dump({"snapshot": result}, sys.stdout)
    except BaseException as error:
        # Exception text may echo key material. Only known-safe codes leave this process.
        status = getattr(error, "status", None)
        code = getattr(error, "code", None)
        safe_code = code if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_]{1,80}", code) else None
        json.dump({"error": "Collection failed. Check the signing key, passphrase, OCIDs, region and reader permissions.",
                   "status": status if isinstance(status, int) else None, "code": safe_code}, sys.stdout)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
