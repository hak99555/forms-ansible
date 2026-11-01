"""Command line entry point; JSON is the default lossless report format."""

import argparse
import csv
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__
from .inventory import (checks, compartment_paths, diff_snapshots, group_policies, list_resources,
                        load_snapshot, merge_snapshots, policy_rows, summary, tree, user_groups, validate_snapshot)


def csv_text(value):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("CSV requires a list report (groups, domains, policies, compartments, resources, checks). Use JSON for nested reports.")
    fields = list(dict.fromkeys(k for row in value for k in row))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in value:
        safe = {}
        for key, item in row.items():
            cell = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else "" if item is None else str(item)
            # Make exports safe to open as a spreadsheet without executing formulas.
            safe[key] = "'" + cell if cell.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else cell
        writer.writerow(safe)
    return stream.getvalue()


def emit(value, args):
    if isinstance(value, str):
        content = value + "\n"
    elif args.format == "csv":
        content = csv_text(value)
    else:
        content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
    else:
        sys.stdout.write(content)


def output_options(parser, csv_allowed=True):
    parser.add_argument("--out", help="Write a UTF-8 report instead of stdout")
    parser.add_argument("--format", choices=["json", "csv"] if csv_allowed else ["json"], default="json")


def ensure_data_only(plan):
    """A collector must never apply a plan involving managed infrastructure."""
    for change in plan.get("resource_changes", []):
        if change.get("mode") != "data":
            raise ValueError(f'Refusing a plan with managed infrastructure: {change.get("address", "unknown")}')
    if plan.get("deferred_changes"):
        raise ValueError("Refusing a deferred/incomplete plan")


def collect(args):
    directory = Path(args.terraform_dir).resolve()
    base = [args.terraform_bin, f"-chdir={directory}"]
    # Temporary plan files include administrative data and are cleaned up on exit.
    with tempfile.TemporaryDirectory(prefix="oci-inventory-") as temp:
        plan_path = str(Path(temp) / "inventory.tfplan")
        flags = [f"-var-file={Path(args.var_file).resolve()}"] if args.var_file else []
        if args.region:
            flags.append(f"-var=region={args.region}")
        subprocess.run(base + ["plan", "-input=false", "-no-color", f"-out={plan_path}"] + flags,
                       check=True, stdout=sys.stderr, stderr=sys.stderr)
        shown = subprocess.run(base + ["show", "-json", plan_path], check=True, capture_output=True, encoding="utf-8")
        ensure_data_only(json.loads(shown.stdout))
        subprocess.run(base + ["apply", "-input=false", "-no-color", plan_path],
                       check=True, stdout=sys.stderr, stderr=sys.stderr)
    exported = subprocess.run(base + ["output", "-json", "inventory"], check=True, capture_output=True, encoding="utf-8")
    data = json.loads(exported.stdout)
    validate_snapshot(data)
    return data


def build_parser():
    parser = argparse.ArgumentParser(description="Read-only OCI Terraform inventory reports and Identity Domains lookups")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("summary", "Counts and collection coverage"), ("groups", "Identity Domain groups"),
        ("domains", "Discovered Identity Domains"), ("policies", "All statements with scope and parse status"),
        ("compartments", "Compartment paths"), ("tree", "Compartment/resource tree"),
        ("resources", "ADB, OIC and bucket inventory"), ("group-policies", "Policy candidates for a group"),
        ("user-groups", "Collected direct memberships for a user"), ("checks", "Configuration review findings"),
    ):
        cmd = commands.add_parser(name, help=help_text)
        cmd.add_argument("snapshot", help="terraform output -json inventory file")
        output_options(cmd, name not in ("summary", "tree", "group-policies", "user-groups"))
        if name in ("group-policies", "user-groups"):
            cmd.add_argument("query", help="Exact name, Domain/name, SCIM ID or OCID")
            cmd.add_argument("--domain", help="Identity Domain name or OCID to disambiguate")
        if name == "groups":
            cmd.add_argument("--domain", help="Exact Identity Domain name or OCID")
        if name == "resources":
            cmd.add_argument("--kind", choices=["adb", "oic", "bucket"])
            cmd.add_argument("--region")
            cmd.add_argument("--compartment", help="OCID, exact name, or full compartment path")
            cmd.add_argument("--descendants", action="store_true", help="Include descendants of --compartment")
        if name == "tree":
            cmd.add_argument("--compartments-only", action="store_true")
        if name == "checks":
            cmd.add_argument("--required-tag", action="append", default=[], help="Repeat for multiple freeform keys or Namespace.Key names")
            cmd.add_argument("--fail-on-warning", action="store_true", help="Return exit code 2 if a warning is found")
    cmd = commands.add_parser("merge", help="Merge regional snapshots, rejecting conflicting observations")
    cmd.add_argument("snapshots", nargs="+")
    output_options(cmd, False)
    cmd = commands.add_parser("diff", help="Compare observations with matching coverage")
    cmd.add_argument("before")
    cmd.add_argument("after")
    cmd.add_argument("--allow-scope-change", action="store_true")
    output_options(cmd, False)
    cmd = commands.add_parser("export", help="Export the current Terraform output without shell encoding problems")
    cmd.add_argument("--terraform-dir", default="terraform")
    cmd.add_argument("--terraform-bin", default="terraform")
    output_options(cmd, False)
    cmd = commands.add_parser("collect", help="Plan, verify data-only configuration, apply reads to local state, export snapshot")
    cmd.add_argument("--terraform-dir", default="terraform")
    cmd.add_argument("--terraform-bin", default="terraform")
    cmd.add_argument("--var-file", help="Optional tfvars path, relative to the current shell directory")
    cmd.add_argument("--region", help="Override region for this collection")
    output_options(cmd, False)
    cmd = commands.add_parser("live-user-groups", help="Read current direct user memberships through the optional OCI SDK")
    cmd.add_argument("user")
    cmd.add_argument("--domain-url", required=True)
    cmd.add_argument("--by", choices=["name", "id", "ocid"], default="name")
    cmd.add_argument("--profile", default="DEFAULT")
    cmd.add_argument("--config-file", default="~/.oci/config")
    cmd.add_argument("--auth", choices=["api-key", "security-token", "instance-principal", "resource-principal"], default="api-key")
    output_options(cmd, False)
    return parser


def dispatch(args):
    command = args.command
    if command == "collect":
        return collect(args)
    if command == "export":
        result = subprocess.run([args.terraform_bin, f"-chdir={args.terraform_dir}", "output", "-json", "inventory"],
                                check=True, capture_output=True, encoding="utf-8")
        data = json.loads(result.stdout)
        validate_snapshot(data)
        return data
    if command == "merge":
        return merge_snapshots([load_snapshot(p) for p in args.snapshots])
    if command == "diff":
        return diff_snapshots(load_snapshot(args.before), load_snapshot(args.after), args.allow_scope_change)
    if command == "live-user-groups":
        from .live import domain_client, live_user_groups
        try:
            client = domain_client(args.domain_url, args.config_file, args.profile, args.auth)
            return live_user_groups(client, args.user, args.by)
        except Exception as error:
            if isinstance(error, (ValueError, OSError)):
                raise
            # Keep service error code and request ID useful without dumping HTTP headers/credentials.
            status, code, request_id = (getattr(error, key, None) for key in ("status", "code", "request_id"))
            raise ValueError(f"OCI query failed ({type(error).__name__}); status={status}, code={code}, opc-request-id={request_id}. Check credentials, endpoint and domain read permissions.") from error
    data = load_snapshot(args.snapshot)
    if command == "summary":
        return summary(data)
    if command == "groups":
        rows = data["groups"]
        if args.domain:
            rows = [g for g in rows if args.domain.casefold() in (g["domain_id"].casefold(), g["domain_name"].casefold())]
        return sorted(rows, key=lambda g: (g["domain_name"], g["name"]))
    if command == "domains":
        return data["domains"]
    if command == "policies":
        return policy_rows(data)
    if command == "compartments":
        paths = compartment_paths(data)
        return [dict(c, path=paths[c["id"]]) for c in data["compartments"]]
    if command == "tree":
        return tree(data, not args.compartments_only)
    if command == "resources":
        if args.descendants and not args.compartment:
            raise ValueError("--descendants requires --compartment")
        return list_resources(data, args.kind, args.region, args.compartment, args.descendants)
    if command == "group-policies":
        return group_policies(data, args.query, args.domain)
    if command == "user-groups":
        return user_groups(data, args.query, args.domain)
    if command == "checks":
        return checks(data, args.required_tag)
    raise ValueError(f"Unknown command: {command}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = dispatch(args)
        emit(result, args)
        if args.command == "checks" and args.fail_on_warning and any(r["severity"] == "warning" for r in result):
            return 2
        return 0
    except subprocess.CalledProcessError as error:
        print(f"error: Terraform command failed (exit {error.returncode}): {(error.stderr or '').strip()}", file=sys.stderr)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
    return 1
