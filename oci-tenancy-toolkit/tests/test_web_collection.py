import copy
import http.client
import json
import subprocess
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from oci_admin.snapshot_worker import collect, validate_request
from oci_admin.web_server import LocalServer, run_worker


def credentials():
    return {"tenancy_ocid": "ocid1.tenancy.oc1..fake", "user_ocid": "ocid1.user.oc1..fake",
            "fingerprint": ":".join(["aa"] * 16), "private_key": "-----BEGIN PRIVATE KEY-----\n" + "FAKE_TEST_DATA" * 8 + "\n-----END PRIVATE KEY-----",
            "passphrase": "test-only-not-a-real-secret", "home_region": "ca-toronto-1", "regions": ["ca-toronto-1"],
            "services": ["adb", "oic", "buckets"], "include_identity": False, "bucket_details": True}


class LocalEndpointTests(unittest.TestCase):
    def setUp(self):
        self.worker = Mock(return_value={"snapshot": {"collected_at": "now"}})
        self.server = LocalServer(0, worker=self.worker)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        conn.request(method, path, body, headers or {})
        response = conn.getresponse()
        value = response.read()
        result = response.status, dict(response.getheaders()), value
        conn.close()
        return result

    def valid_headers(self):
        return {"Origin": self.server.origin, "X-OCI-Session": self.server.csrf, "Content-Type": "application/json"}

    def test_session_and_assets_are_uncached_without_cors(self):
        status, headers, body = self.request("GET", "/api/session")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["token"], self.server.csrf)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("GET", "/../pyproject.toml")[0], 404)

    def test_cross_origin_missing_token_and_rebinding_are_rejected(self):
        for headers in ({}, dict(self.valid_headers(), Origin="https://other.example"),
                        dict(self.valid_headers(), Host="attacker.example"),
                        dict(self.valid_headers(), **{"X-OCI-Session": "wrong"})):
            self.assertEqual(self.request("POST", "/api/snapshot", json.dumps(credentials()), headers)[0], 403)
        self.worker.assert_not_called()

    def test_credentials_only_pass_to_worker_and_not_response(self):
        body = json.dumps(credentials())
        status, _, response = self.request("POST", "/api/snapshot", body, self.valid_headers())
        self.assertEqual(status, 200)
        self.assertEqual(self.worker.call_args.args[0], body.encode())
        self.assertNotIn(b"PRIVATE KEY", response)
        self.assertNotIn(credentials()["passphrase"].encode(), response)

    def test_bad_body_and_large_requests_do_not_reach_worker(self):
        self.assertEqual(self.request("POST", "/api/snapshot", "{}", self.valid_headers())[0], 400)
        self.assertEqual(self.request("POST", "/api/snapshot", "x" * 70000, self.valid_headers())[0], 413)
        headers = dict(self.valid_headers(), **{"Content-Type": "text/plain"})
        self.assertEqual(self.request("POST", "/api/snapshot", "{}", headers)[0], 415)
        self.worker.assert_not_called()

    def test_worker_failure_does_not_echo_exception(self):
        self.worker.side_effect = RuntimeError(credentials()["private_key"])
        status, _, body = self.request("POST", "/api/snapshot", json.dumps(credentials()), self.valid_headers())
        self.assertEqual(status, 500)
        self.assertNotIn(b"PRIVATE KEY", body)


class WorkerTests(unittest.TestCase):
    def test_rejects_custom_endpoint_and_invalid_request_fields(self):
        for key, value in (("home_region", "https://attacker.example"), ("regions", []), ("private_key", "wrong"),
                           ("fingerprint", "abc"), ("services", ["delete"]), ("include_identity", "true")):
            data = credentials()
            data[key] = value
            with self.assertRaises((ValueError, TypeError)):
                validate_request(data)

    @patch("oci_admin.web_server.subprocess.Popen")
    def test_worker_uses_stdin_and_discards_stderr(self, popen):
        process = popen.return_value
        process.communicate.return_value = (b'{"snapshot":{}}', None)
        process.poll.return_value = 0
        body = json.dumps(credentials()).encode()
        self.assertEqual(run_worker(body), {"snapshot": {}})
        args, kwargs = popen.call_args
        self.assertNotIn("PRIVATE KEY", str(args))
        self.assertNotIn(credentials()["passphrase"], str(kwargs["env"]))
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(process.communicate.call_args.args, (body,))

    @patch("oci_admin.web_server.subprocess.Popen")
    def test_timeout_terminates_signing_process(self, popen):
        process = popen.return_value
        process.communicate.side_effect = [subprocess.TimeoutExpired("worker", 1), (b"", None)]
        process.poll.return_value = 1
        self.assertIn("terminated", run_worker(b"test", timeout=1)["error"])
        process.kill.assert_called_once()

    def test_mock_sdk_snapshot_is_compatible_and_credentials_are_cleared(self):
        request = credentials()
        identity, database, integration, storage, scim = Mock(), Mock(), Mock(), Mock(), Mock()
        identity.get_tenancy.return_value.data = NS(name="TestTenancy")
        identity.list_region_subscriptions.return_value.data = [NS(region_name="ca-toronto-1", region_key="YYZ", is_home_region=True, status="READY")]
        identity.list_compartments.return_value.data = []
        identity.list_policies.return_value.data = [NS(id="p", name="Reader", compartment_id=request["tenancy_ocid"], description="Reader", statements=[])]
        identity.list_domains.return_value.data = [NS(id="d", display_name="Default", url="https://test.identity.oraclecloud.com", home_region="ca-toronto-1", compartment_id=request["tenancy_ocid"], lifecycle_state="ACTIVE")]
        scim.list_groups.return_value.data = NS(resources=[NS(id="g", ocid="ocid1.group.oc1..fake", display_name="Readers")], total_results=1, start_index=1)
        database.list_autonomous_databases.return_value.data = [NS(id="a", display_name="ADB", compartment_id=request["tenancy_ocid"], lifecycle_state="AVAILABLE")]
        integration.list_integration_instances.return_value.data = [NS(id="i", display_name="OIC", compartment_id=request["tenancy_ocid"], lifecycle_state="ACTIVE")]
        storage.get_namespace.return_value.data = "namespace"
        storage.list_buckets.return_value.data = [NS(name="bucket", compartment_id=request["tenancy_ocid"])]
        storage.get_bucket.return_value.data = NS(public_access_type="NoPublicAccess", versioning="Enabled")
        sdk = NS(signer=NS(Signer=Mock()), retry=NS(DEFAULT_RETRY_STRATEGY=None),
                 identity=NS(IdentityClient=Mock(return_value=identity)), database=NS(DatabaseClient=Mock(return_value=database)),
                 integration=NS(IntegrationInstanceClient=Mock(return_value=integration)), object_storage=NS(ObjectStorageClient=Mock(return_value=storage)),
                 identity_domains=NS(IdentityDomainsClient=Mock(return_value=scim)),
                 pagination=NS(list_call_get_all_results=lambda method, **kwargs: method(**kwargs)),
                 util=NS(to_dict=lambda value: value))
        request["include_identity"] = True
        result = collect(request, sdk)
        self.assertEqual({r["kind"] for r in result["resources"]}, {"adb", "oic", "bucket"})
        self.assertEqual(result["groups"][0]["name"], "Readers")
        self.assertEqual(request, {})
        self.assertNotIn("PRIVATE KEY", json.dumps(result))
        self.assertNotIn(credentials()["passphrase"], json.dumps(result))
        for instance in (identity, database, integration, storage, scim):
            self.assertTrue(instance.base_client.session.close.called)
        signer_kwargs = sdk.signer.Signer.call_args.kwargs
        self.assertIsNone(signer_kwargs["private_key_file_location"])
        self.assertIn("PRIVATE KEY", signer_kwargs["private_key_content"])
