"""Snapshot validation, navigation, reporting, checks and comparison."""

import copy
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .policy import matches_group, parse_statement

COLLECTIONS = ("regions", "compartments", "policies", "domains", "groups", "users", "memberships", "resources")


def load_snapshot(path):
    # Windows PowerShell 5 redirection may produce UTF-16; modern exports use UTF-8.
    raw = Path(path).read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    data = json.loads(raw.decode(encoding))
    if isinstance(data, dict) and "inventory" in data and isinstance(data["inventory"], dict):
        data = data["inventory"].get("value", data["inventory"])
    validate_snapshot(data)
    return data


def validate_snapshot(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Expected schema_version 1; export with terraform output -json inventory")
    if not isinstance(data.get("tenancy"), dict) or not data["tenancy"].get("id"):
        raise ValueError("Snapshot is missing tenancy.id")
    if not isinstance(data.get("coverage"), dict):
        raise ValueError("Snapshot is missing coverage metadata")
    for key in COLLECTIONS:
        if not isinstance(data.get(key), list):
            raise ValueError(f"Snapshot is missing list: {key}")
        keys = [record_key(key, row) for row in data[key]]
        if len(set(keys)) != len(keys):
            raise ValueError(f"Duplicate record identities in {key}")


def record_key(collection, row):
    if collection == "resources":
        return (row["kind"], row["region"], row["id"])
    if collection == "memberships":
        return (row["domain_id"], row["user_id"], row["group_id"])
    if collection in ("groups", "users"):
        return (row["domain_id"], row["id"])
    if collection == "regions":
        return (row["region_name"],)
    return (row["id"],)


def compartment_paths(snapshot):
    by_id = {c["id"]: c for c in snapshot["compartments"]}
    paths = {}

    def visit(cid, visiting):
        if cid in paths:
            return paths[cid]
        if cid in visiting:
            raise ValueError(f"Compartment cycle at {cid}")
        c = by_id.get(cid)
        if c is None:
            return f"[unknown:{cid}]"
        parent = c.get("compartment_id")
        prefix = visit(parent, visiting | {cid}) + "/" if parent else ""
        paths[cid] = prefix + c["name"]
        return paths[cid]

    for cid in by_id:
        visit(cid, set())
    return paths


def select_one(rows, query, label, domain=None):
    candidates = []
    for row in rows:
        if domain and domain.casefold() not in (row.get("domain_name", "").casefold(), row.get("domain_id", "").casefold()):
            continue
        names = [row.get("id", ""), row.get("ocid", ""), row.get("name", "")]
        if row.get("domain_name"):
            names.append(f'{row["domain_name"]}/{row["name"]}')
        if query.casefold() in [str(n).casefold() for n in names if n]:
            candidates.append(row)
    if not candidates:
        raise ValueError(f"{label} not found in collected data: {query}")
    if len(candidates) > 1:
        raise ValueError(f"Ambiguous {label}: {query}; specify its OCID or Domain/name")
    return candidates[0]


def list_resources(snapshot, kind=None, region=None, compartment=None, descendants=False):
    paths = compartment_paths(snapshot)
    ids = None
    if compartment:
        exact = [c for c in snapshot["compartments"] if paths[c["id"]] == compartment]
        c = exact[0] if len(exact) == 1 else select_one(snapshot["compartments"], compartment, "compartment")
        ids = {c["id"]}
        if descendants:
            children = defaultdict(list)
            for row in snapshot["compartments"]:
                children[row.get("compartment_id")].append(row["id"])
            pending = [c["id"]]
            while pending:
                for cid in children[pending.pop()]:
                    if cid not in ids:
                        ids.add(cid)
                        pending.append(cid)
    return sorted([
        dict(r, compartment_path=paths.get(r["compartment_id"], f'[unknown:{r["compartment_id"]}]'))
        for r in snapshot["resources"]
        if (not kind or r["kind"] == kind) and (not region or r["region"] == region)
        and (ids is None or r["compartment_id"] in ids)
    ], key=lambda r: (r["compartment_path"], r["region"], r["kind"], r["name"], r["id"]))


def tree(snapshot, include_resources=True):
    paths = compartment_paths(snapshot)
    resources = defaultdict(list)
    for r in list_resources(snapshot):
        resources[r["compartment_id"]].append(r)
    lines = []
    for cid, path in sorted(paths.items(), key=lambda item: item[1]):
        lines.append(f"{path}  [{cid}]")
        if include_resources:
            for r in resources[cid]:
                lines.append(f'  |-- {r["kind"]}: {r["name"]} ({r["region"]}; {r.get("state") or "n/a"})')
    unknown = set(resources) - set(paths)
    for cid in sorted(unknown):
        lines.append(f"[unknown:{cid}]")
        lines.extend(f'  |-- {r["kind"]}: {r["name"]} ({r["region"]})' for r in resources[cid])
    return "\n".join(lines)


def user_groups(snapshot, query, domain=None):
    user = select_one(snapshot["users"], query, "collected user (configure user_queries or use live-user-groups)", domain)
    gids = {m["group_id"] for m in snapshot["memberships"]
            if m["domain_id"] == user["domain_id"] and m["user_id"] == user["id"]}
    groups = [g for g in snapshot["groups"] if g["domain_id"] == user["domain_id"] and g["id"] in gids]
    missing = gids - {g["id"] for g in groups}
    if missing:
        raise ValueError(f"Membership refers to uncollected groups: {sorted(missing)}")
    return {"user": user, "membership_semantics": "direct-scim-members-filter", "groups": groups,
            "note": "Implicit All Domain Users membership, application roles and indirect entitlements are not evaluated."}


def policy_rows(snapshot):
    paths = compartment_paths(snapshot)
    rows = []
    for policy in snapshot["policies"]:
        for index, statement in enumerate(policy["statements"], start=1):
            rows.append({"policy_id": policy["id"], "policy_name": policy["name"],
                         "attachment_id": policy["compartment_id"],
                         "attachment_path": paths.get(policy["compartment_id"], "[unknown]"),
                         "statement_number": index, "statement": statement, **parse_statement(statement)})
    return rows


def group_policies(snapshot, query, domain=None):
    group = select_one(snapshot["groups"], query, "group", domain)
    matches, broad, unsupported = [], [], []
    for row in policy_rows(snapshot):
        if not row["parsed"]:
            unsupported.append(row)
        elif matches_group(row, group):
            matches.append(row)
        elif row["subject_kind"] in ("any-user", "any-group"):
            broad.append(row)
    return {"group": group, "matches": matches, "broad_principal_candidates": broad,
            "unparsed_statements": unsupported,
            "note": "Declared policy candidates, not effective access. Conditions, request context, scope inheritance, cross-tenancy agreements and application roles require separate evaluation."}


def summary(snapshot):
    scanned = set(snapshot["coverage"].get("regions", []))
    subscribed = {r["region_name"] for r in snapshot["regions"] if r.get("status") == "READY"}
    return {"tenancy": snapshot["tenancy"], "collected_at": snapshot.get("collected_at"),
            "counts": {k: len(snapshot[k]) for k in COLLECTIONS},
            "resources_by_kind": dict(Counter(r["kind"] for r in snapshot["resources"])),
            "resources_by_region": dict(Counter(r["region"] for r in snapshot["resources"])),
            "unscanned_subscribed_regions": sorted(subscribed - scanned), "coverage": snapshot["coverage"]}


def checks(snapshot, required_tags=()):
    findings = []

    def add(code, severity, target, message, evidence=None):
        findings.append({"code": code, "severity": severity, "target": target, "message": message, "evidence": evidence})

    for region in summary(snapshot)["unscanned_subscribed_regions"]:
        add("REGION_NOT_SCANNED", "info", region, "Subscribed region is outside this snapshot's inventory scope.")
    if snapshot["coverage"].get("incomplete"):
        add("INCOMPLETE_SNAPSHOT", "warning", "coverage", "Snapshot reports incomplete collection.")
    if not snapshot["coverage"].get("identity_domains"):
        add("IDENTITY_NOT_SCANNED", "info", "coverage", "Identity Domain collection was disabled.")
    for r in snapshot["resources"]:
        target = f'{r["kind"]}:{r["region"]}:{r["name"]}'
        detail = r.get("details") or {}
        if r.get("state") in ("FAILED", "UNAVAILABLE", "INACCESSIBLE", "RESTORE_FAILED"):
            add("RESOURCE_UNHEALTHY", "warning", target, "Investigate the service lifecycle state.",
                {"state": r["state"], "lifecycle_details": detail.get("lifecycle_details")})
        if r["kind"] == "bucket":
            if not detail.get("details_collected"):
                add("BUCKET_DETAILS_SKIPPED", "info", target, "Public access and versioning checks could not run.")
            else:
                access = detail.get("public_access_type")
                if access in ("ObjectRead", "ObjectReadWithoutList"):
                    add("BUCKET_PUBLIC", "warning", target, "Bucket allows public object reads; confirm this is intended.", access)
                if detail.get("versioning") in ("Disabled", "Suspended"):
                    add("BUCKET_VERSIONING", "info", target, "New object versions are not being retained by versioning.", detail["versioning"])
        if r["kind"] == "adb" and not detail.get("private_endpoint") and not detail.get("subnet_id"):
            add("ADB_PUBLIC_ENDPOINT_REVIEW", "info", target,
                "No private endpoint/subnet is recorded. Review ACLs and connectivity; this does not prove internet reachability.",
                {"is_access_control_enabled": detail.get("is_access_control_enabled"), "whitelisted_ips": detail.get("whitelisted_ips")})
        tags = dict(r.get("freeform_tags") or {})
        # Terraform flattens defined tags; SDK-style nested namespaces are also accepted.
        for name, value in (r.get("defined_tags") or {}).items():
            if isinstance(value, dict):
                tags.update({f"{name}.{k}": v for k, v in value.items()})
            else:
                tags[name] = value
        missing = [tag for tag in required_tags if tags.get(tag) in (None, "")]
        if missing:
            add("MISSING_TAGS", "info", target, "Required reporting tags are absent or empty.", missing)
    for row in policy_rows(snapshot):
        target = f'{row["policy_name"]}#{row["statement_number"]}'
        if not row["parsed"]:
            add("POLICY_MANUAL_REVIEW", "info", target, row["reason"], row["statement"])
        elif row["verb"].casefold() == "manage" and row["resource_type"].casefold() == "all-resources" and row["scope"].casefold() == "tenancy":
            add("TENANCY_ADMIN_STATEMENT", "warning", target, "Broad administrative statement; review its subject and conditions.", row["statement"])
    return findings


def canonical(value):
    """Treat collection order as immaterial for snapshot comparisons."""
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return sorted((canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def merge_snapshots(snapshots):
    if not snapshots:
        raise ValueError("Provide at least one snapshot")
    if len({s["tenancy"]["id"] for s in snapshots}) != 1:
        raise ValueError("Cannot merge snapshots from different tenancies")
    merged = copy.deepcopy(snapshots[0])
    for collection in COLLECTIONS:
        records = {}
        for snapshot in snapshots:
            for row in snapshot[collection]:
                key = record_key(collection, row)
                if key in records and canonical(records[key]) != canonical(row):
                    raise ValueError(f"Conflicting {collection} record {key}; recollect consistent snapshots")
                records[key] = row
        merged[collection] = [records[k] for k in sorted(records)]
    # Retain per-region coverage. Do not imply that a union of service/compartment
    # scopes was actually scanned in every region.
    scopes = []
    for snapshot in snapshots:
        coverage = snapshot["coverage"]
        scopes.extend(coverage.get("scans", [coverage]))
    merged["coverage"] = {
        "regions": sorted({r for c in scopes for r in c.get("regions", [])}),
        "identity_domains": all(c.get("identity_domains", False) for c in scopes),
        "incomplete": any(c.get("incomplete", False) for c in scopes),
        "scans": scopes,
    }
    merged["source_timestamps"] = [s.get("collected_at") for s in snapshots]
    merged["collected_at"] = datetime.now(timezone.utc).isoformat()
    return merged


def diff_snapshots(before, after, allow_scope_change=False):
    if before["tenancy"]["id"] != after["tenancy"]["id"]:
        raise ValueError("Cannot compare different tenancies")
    scope_changed = canonical(before["coverage"]) != canonical(after["coverage"])
    if scope_changed and not allow_scope_change:
        raise ValueError("Collection coverage differs. Recollect matching scopes or explicitly use --allow-scope-change.")
    changes = []
    for collection in COLLECTIONS:
        old = {record_key(collection, r): r for r in before[collection]}
        new = {record_key(collection, r): r for r in after[collection]}
        for key in sorted(old.keys() | new.keys()):
            action = "added" if key not in old else "removed" if key not in new else "changed"
            if action == "changed" and canonical(old[key]) == canonical(new[key]):
                continue
            changes.append({"collection": collection, "key": list(key), "change": action,
                            "before": old.get(key), "after": new.get(key)})
    return {"scope_changed": scope_changed, "changes": changes,
            "note": "Differences are observations between snapshots, not proof of resource creation/deletion or a continuous audit trail."}
