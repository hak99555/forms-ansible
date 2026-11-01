import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

from oci_admin.cli import csv_text, ensure_data_only, main
from oci_admin.inventory import (checks, compartment_paths, diff_snapshots, group_policies, list_resources,
                                 load_snapshot, merge_snapshots, summary, tree, user_groups)
from oci_admin.live import live_user_groups, scim_pages
from oci_admin.policy import matches_group, parse_statement

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "demo.snapshot.json"


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.group = {"name": "Ops", "domain_name": "Workforce", "ocid": "ocid1.group.oc1..ops"}

    def matched(self, statement):
        return matches_group(parse_statement(statement), self.group)

    def test_domain_qualified_group(self):
        self.assertTrue(self.matched("Allow group 'Workforce'/'Ops' to read buckets in tenancy"))
        self.assertTrue(self.matched("ALLOW group 'workforce/Ops' to READ buckets in tenancy"))

    def test_default_domain_never_matches_same_name_in_another_domain(self):
        self.assertFalse(self.matched("Allow group Ops to read buckets in tenancy"))
        self.assertFalse(self.matched("Allow group Default/Ops to read buckets in tenancy"))

    def test_group_ocid(self):
        self.assertTrue(self.matched("Allow group id ocid1.group.oc1..ops to read buckets in tenancy"))
        self.assertFalse(self.matched("Allow group id ocid1.group.oc1..ops2 to read buckets in tenancy"))

    def test_multiple_subjects(self):
        self.assertTrue(self.matched("Allow group id ocid1.group.oc1..other, 'Workforce'/'Ops' to use objects in tenancy"))

    def test_no_substring_matches_or_conditions(self):
        self.assertFalse(self.matched("Allow group Workforce/OpsAdmin to read buckets in tenancy"))
        self.assertFalse(self.matched("Allow group Other to read buckets in tenancy where target.group.name = 'Workforce/Ops'"))

    def test_quote_aware_names(self):
        group = dict(self.group, name="Move to Cloud, Operations")
        parsed = parse_statement("Allow group 'Workforce'/'Move to Cloud, Operations' to read buckets in tenancy where target.bucket.name = 'x in y'")
        self.assertTrue(matches_group(parsed, group))
        self.assertEqual(parsed["conditions"], "target.bucket.name = 'x in y'")

    def test_permissions_and_multiline(self):
        parsed = parse_statement("Allow\n group Workforce/Ops to {BUCKET_READ, BUCKET_INSPECT} in compartment Production where all {request.region='YYZ', target.bucket.name='Ops'}")
        self.assertTrue(parsed["parsed"])
        self.assertEqual(parsed["verb"], "{BUCKET_READ, BUCKET_INSPECT}")

    def test_cross_tenancy_and_malformed_are_reported(self):
        for text in ("Endorse group Ops to read objects in tenancy Partner", "Allow group 'Oops to read buckets in tenancy", "Allow group Ops to read buckets"):
            self.assertFalse(parse_statement(text)["parsed"])

    def test_other_principals_do_not_match_human_groups(self):
        self.assertFalse(self.matched("Allow dynamic-group Workforce/Ops to read buckets in tenancy"))
        self.assertEqual(parse_statement("Allow any-user to read buckets in tenancy")["subject_kind"], "any-user")


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.data = load_snapshot(FIXTURE)

    def test_tree_includes_root_and_nested_resources(self):
        rendered = tree(self.data)
        self.assertIn("DemoTenancy/Production/Applications", rendered)
        self.assertIn("oic: ERPIntegration", rendered)

    def test_cycles_fail_cleanly(self):
        self.data["compartments"][0]["compartment_id"] = self.data["compartments"][2]["id"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            compartment_paths(self.data)

    def test_missing_parent_is_explicit(self):
        self.data["compartments"][1]["compartment_id"] = "missing"
        self.assertIn("[unknown:missing]", tree(self.data))

    def test_compartment_filters_and_descendants(self):
        self.assertEqual(len(list_resources(self.data, compartment="Production")), 2)
        self.assertEqual(len(list_resources(self.data, compartment="Production", descendants=True)), 3)
        self.assertEqual(len(list_resources(self.data, kind="oic")), 1)
        self.assertEqual(len(list_resources(self.data, region="ca-montreal-1")), 0)

    def test_ambiguous_group_rejected(self):
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            group_policies(self.data, "OCI-Operators")

    def test_policy_candidates_and_manual_review(self):
        report = group_policies(self.data, "Workforce/OCI-Operators")
        self.assertEqual(len(report["matches"]), 3)
        self.assertEqual(len(report["broad_principal_candidates"]), 1)
        self.assertEqual(len(report["unparsed_statements"]), 2)
        self.assertTrue(any(row["conditions"] for row in report["matches"]))

    def test_memberships(self):
        self.assertEqual(user_groups(self.data, "alice@example.com")["groups"][0]["domain_name"], "Workforce")
        with self.assertRaisesRegex(ValueError, "not found"):
            user_groups(self.data, "uncollected@example.com")

    def test_public_bucket_and_coverage(self):
        codes = [r["code"] for r in checks(self.data, ["Owner"])]
        for code in ("BUCKET_PUBLIC", "MISSING_TAGS", "RESOURCE_UNHEALTHY", "REGION_NOT_SCANNED", "TENANCY_ADMIN_STATEMENT"):
            self.assertIn(code, codes)
        self.assertNotIn("ADB_PUBLIC_ENDPOINT_REVIEW", codes)
        self.assertEqual(summary(self.data)["unscanned_subscribed_regions"], ["ca-montreal-1"])

    def test_uncollected_bucket_details_do_not_pass_as_safe(self):
        self.data["resources"][2]["details"] = {"details_collected": False}
        codes = [r["code"] for r in checks(self.data)]
        self.assertIn("BUCKET_DETAILS_SKIPPED", codes)
        self.assertNotIn("BUCKET_PUBLIC", codes)

    def test_diff_ignores_order_and_timestamp(self):
        after = copy.deepcopy(self.data)
        after["collected_at"] = "new time"
        after["groups"].reverse()
        after["policies"][1]["statements"].reverse()
        self.assertEqual(diff_snapshots(self.data, after)["changes"], [])
        after["resources"][2]["details"]["versioning"] = "Enabled"
        self.assertEqual(len(diff_snapshots(self.data, after)["changes"]), 1)

    def test_diff_rejects_scope_mismatch(self):
        after = copy.deepcopy(self.data)
        after["coverage"]["regions"] = ["ca-montreal-1"]
        with self.assertRaisesRegex(ValueError, "coverage"):
            diff_snapshots(self.data, after)
        self.assertTrue(diff_snapshots(self.data, after, True)["scope_changed"])

    def test_merge_preserves_region_scopes(self):
        other = copy.deepcopy(self.data)
        other["resources"] = []
        other["coverage"]["regions"] = ["ca-montreal-1"]
        other["coverage"]["services"] = ["adb"]
        result = merge_snapshots([self.data, other])
        self.assertEqual(len(result["groups"]), 3)
        self.assertEqual(len(result["coverage"]["scans"]), 2)
        self.assertEqual(summary(result)["unscanned_subscribed_regions"], [])

    def test_merge_rejects_conflicts_and_other_tenancies(self):
        other = copy.deepcopy(self.data)
        other["resources"][0]["state"] = "STOPPED"
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            merge_snapshots([self.data, other])
        other["tenancy"]["id"] = "another-tenancy"
        with self.assertRaisesRegex(ValueError, "different tenancies"):
            merge_snapshots([self.data, other])

    def test_terraform_wrapped_and_windows_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.json"
            path.write_text(json.dumps({"inventory": {"value": self.data}}), encoding="utf-16")
            self.assertEqual(load_snapshot(path), self.data)


class LiveTests(unittest.TestCase):
    def page(self, ids, total, start):
        return NS(data=NS(resources=[NS(id=i) for i in ids], total_results=total, start_index=start))

    def test_pagination_uses_actual_returned_page_size(self):
        method = Mock(side_effect=[self.page(["a", "b"], 3, 1), self.page(["c"], 3, 3)])
        self.assertEqual([r.id for r in scim_pages(method)], ["a", "b", "c"])
        self.assertEqual(method.call_args_list[1].kwargs["start_index"], 3)

    def test_empty_and_truncated_pages(self):
        self.assertEqual(scim_pages(Mock(return_value=self.page([], 0, 1))), [])
        with self.assertRaisesRegex(ValueError, "empty page"):
            scim_pages(Mock(return_value=self.page([], 2, 1)))

    def test_duplicate_and_changing_total_fail(self):
        for pages in ([self.page(["a"], 2, 1), self.page(["a"], 2, 2)],
                      [self.page(["a"], 2, 1), self.page(["b"], 3, 2)]):
            with self.assertRaises(ValueError):
                scim_pages(Mock(side_effect=pages))

    def test_live_query_escapes_user_name_and_filters_by_scim_id(self):
        user = NS(id="u1", ocid="ocid1.user.test", user_name='a"b', active=True)
        client = NS(list_users=Mock(return_value=NS(data=NS(resources=[user], total_results=1, start_index=1))),
                    list_groups=Mock(return_value=self.page([], 0, 1)))
        report = live_user_groups(client, 'a"b')
        self.assertEqual(client.list_users.call_args.kwargs["filter"], 'userName eq "a\\"b"')
        self.assertEqual(client.list_groups.call_args.kwargs["filter"], 'members.value eq "u1"')
        self.assertEqual(report["groups"], [])


class CommandTests(unittest.TestCase):
    def test_offline_command_and_exit_codes(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["groups", str(FIXTURE)]), 0)
        self.assertEqual(len(json.loads(out.getvalue())), 3)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["checks", str(FIXTURE), "--fail-on-warning"]), 2)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["user-groups", str(FIXTURE), "nobody"]), 1)

    def test_csv_formula_protection_and_nested_json(self):
        text = csv_text([{"name": "=1+1", "details": {"a": 1}}])
        self.assertIn("'=1+1", text)
        with self.assertRaises(ValueError):
            csv_text({"nested": []})

    def test_collector_refuses_managed_resources_even_if_noop(self):
        ensure_data_only({"resource_changes": [{"mode": "data"}]})
        with self.assertRaisesRegex(ValueError, "managed infrastructure"):
            ensure_data_only({"resource_changes": [{"mode": "managed", "address": "oci_identity_group.test", "change": {"actions": ["no-op"]}}]})
        with self.assertRaisesRegex(ValueError, "deferred"):
            ensure_data_only({"deferred_changes": [{}]})


if __name__ == "__main__":
    unittest.main()
