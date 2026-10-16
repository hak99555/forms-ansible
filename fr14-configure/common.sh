#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
SUITE_HOME="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SUITE_HOME/env_settings.sh"
log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }
trap 'rc=$?; printf "ERROR: %s line %s exited %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$rc" >&2; exit "$rc"' ERR
require_oracle() { [[ "$(id -un)" == "$ORACLE_USER" ]] || die "Run as $ORACLE_USER"; }
validate_config() {
  python3 - <<'PY'
import os, re, socket
from pathlib import Path
e = os.environ
for key in ("DOMAIN_NAME", "RCU_PREFIX", "MACHINE_NAME", "FORMS_CLUSTER",
            "REPORTS_CLUSTER", "OHS_NAME", "REPORTS_TOOLS_NAME", "REPORTS_SERVER_PREFIX"):
    assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", e[key]), key
assert re.fullmatch(r"[A-Z][A-Z0-9]{0,11}", e["RCU_PREFIX"]), "RCU_PREFIX"
for key in ("ORACLE_HOME", "DOMAIN_HOME", "APPLICATION_HOME", "STATE_HOME",
            "LOG_HOME", "JAVA_HOME", "SUITE_HOME"):
    assert re.fullmatch(r"/[A-Za-z0-9_./-]+", e[key]), key
oh, dh = Path(e["ORACLE_HOME"]).resolve(), Path(e["DOMAIN_HOME"]).resolve()
assert oh != dh and oh not in dh.parents and dh not in oh.parents
assert e["ADMIN_ADDRESS"] == e["NM_ADDRESS"] == "127.0.0.1"
assert e["FORMS_CLUSTER"] != e["REPORTS_CLUSTER"]
assert e["OHS_ENABLED"] in ("true", "false"), "OHS_ENABLED"
ports = [int(e[k]) for k in ("ADMIN_PORT", "NM_PORT")]
if e["OHS_ENABLED"] == "true":
    ports.extend(int(e[k]) for k in ("OHS_PORT", "OHS_SSL_PORT", "OHS_ADMIN_PORT"))
for component in ("FORMS", "REPORTS"):
    count, base = int(e[component + "_COUNT"]), int(e[component + "_PORT_BASE"])
    assert 1 <= count <= 32
    ports.extend(range(base, base + count))
for component in ("ADMIN", "FORMS", "REPORTS"):
    assert 128 <= int(e[component + "_XMS"]) <= int(e[component + "_XMX"])
assert len(set(ports)) == len(ports), "Duplicate listener ports"
assert all(1024 <= p <= 65535 for p in ports)
assert 0 <= int(e["REPORTS_MIN_ENGINE"]) <= int(e["REPORTS_INIT_ENGINE"]) <= int(e["REPORTS_MAX_ENGINE"])
assert int(e["REPORTS_MAX_ENGINE"]) >= 1 and int(e["REPORTS_ENG_LIFE"]) >= 1
socket.getaddrinfo(e["LISTEN_ADDRESS"], None)
PY
}
init_job() {
  require_oracle
  validate_config
  mkdir -p "$STATE_HOME" "$LOG_HOME"
  exec 9>"$STATE_HOME/provision.lock"
  flock -n 9 || die "Another provisioning operation is running"
  exec > >(tee -a "$LOG_HOME/$(basename "$0").log") 2>&1
}
secret() {
  python3 - "$1" <<'PY'
import os, stat, sys
p = sys.argv[1]
s = os.stat(p)
assert stat.S_ISREG(s.st_mode) and s.st_uid == os.geteuid(), "Invalid secret owner/type"
assert stat.S_IMODE(s.st_mode) & 0o077 == 0, "Secret must be private"
value = open(p, encoding="utf-8").read().rstrip("\n")
assert value and "\n" not in value and "\r" not in value, "Invalid secret"
sys.stdout.write(value)
PY
}
verify_media() {
  local file="$1" checksum="$2"
  [[ "$checksum" =~ ^[[:xdigit:]]{64}$ ]] || die "Set the SHA-256 for $file"
  [[ -r "$file" ]] || die "Cannot read $file"
  printf '%s  %s\n' "$checksum" "$file" | sha256sum --check --status || die "SHA-256 mismatch: $file"
}
