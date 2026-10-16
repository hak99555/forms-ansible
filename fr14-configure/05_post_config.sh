#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
[[ "${FR14_CONFIGURE_ACTIVE:-}" == 1 ]] || die "Run configure.sh to hold the provisioning lock"
require_oracle
validate_config
[[ -f "$STATE_HOME/domain.complete" ]] || die "Domain creation incomplete"
grep -q 'setUserOverrides.sh' "$DOMAIN_HOME/bin/setDomainEnv.sh" ||
  die "setDomainEnv.sh lacks the expected user override hook"
mkdir -p "$LOG_HOME"/{gc,heaps}
python3 - <<'PY'
import os, shlex
e = os.environ
path = os.path.join(e["DOMAIN_HOME"], "bin", "fr-memory-settings.sh")
keys = ["ADMIN_XMS", "ADMIN_XMX", "FORMS_XMS", "FORMS_XMX",
        "REPORTS_XMS", "REPORTS_XMX", "JVM_COMMON", "LOG_HOME"]
with open(path, "w") as f:
    f.write("# Generated from env_settings.sh\n")
    for key in keys:
        f.write("export %s=%s\n" % (key, shlex.quote(e[key])))
os.chmod(path, 0o600)
PY
override="$DOMAIN_HOME/bin/setUserOverrides.sh"
if [[ -e "$override" ]] && ! grep -q '^# FR14 AUTOMATION$' "$override"; then
  die "Existing unmanaged setUserOverrides.sh; merge explicitly"
fi
cat > "$override" <<'EOF'
# FR14 AUTOMATION
. "${DOMAIN_HOME}/bin/fr-memory-settings.sh"
case "${SERVER_NAME:-AdminServer}" in
  AdminServer) FR_XMS="$ADMIN_XMS"; FR_XMX="$ADMIN_XMX" ;;
  WLS_FORMS[0-9]*) FR_XMS="$FORMS_XMS"; FR_XMX="$FORMS_XMX" ;;
  WLS_REPORTS[0-9]*) FR_XMS="$REPORTS_XMS"; FR_XMX="$REPORTS_XMX" ;;
  *) printf 'Unknown server: %s\n' "${SERVER_NAME:-unset}" >&2; return 1 ;;
esac
USER_MEM_ARGS="-Xms${FR_XMS}m -Xmx${FR_XMX}m ${JVM_COMMON}"
USER_MEM_ARGS="${USER_MEM_ARGS} -XX:HeapDumpPath=${LOG_HOME}/heaps"
USER_MEM_ARGS="${USER_MEM_ARGS} -Xlog:gc*:file=${LOG_HOME}/gc/${SERVER_NAME:-AdminServer}-%p.log:time,uptime,level,tags:filecount=10,filesize=20M"
export USER_MEM_ARGS
unset FR_XMS FR_XMX
EOF
chmod 0600 "$override"
python3 - <<'PY'
import os
from pathlib import Path
e = os.environ
path = Path(e["DOMAIN_HOME"]) / "nodemanager/nodemanager.properties"
path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
lines = path.read_text().splitlines() if path.exists() else []
updates = {
    "ListenAddress": e["NM_ADDRESS"], "ListenPort": e["NM_PORT"],
    "SecureListener": "false", "AuthenticationEnabled": "true",
    "StartScriptEnabled": "true", "StopScriptEnabled": "false",
    "CrashRecoveryEnabled": "true", "DomainsFileEnabled": "true",
    "DomainsFile": e["DOMAIN_HOME"] + "/nodemanager/nodemanager.domains",
    "LogLimit": "10485760", "LogCount": "10", "LogAppend": "true"
}
kept = [line for line in lines if line.partition("=")[0].strip() not in updates]
kept.extend("%s=%s" % item for item in updates.items())
path.write_text("\n".join(kept) + "\n")
path.chmod(0o600)
domains = path.parent / "nodemanager.domains"
domains.write_text(e["DOMAIN_NAME"] + "=" + e["DOMAIN_HOME"] + "\n")
domains.chmod(0o600)
PY
mkdir -p "$STATE_HOME/units"
# Only known centralized parameters are substituted in service templates.
python3 - <<'PY'
import os
from string import Template
from pathlib import Path
e = dict(os.environ)
e["TOTAL_STOP_TIMEOUT"] = str(int(e["STOP_TIMEOUT"]) *
                            (int(e["FORMS_COUNT"]) + 2 * int(e["REPORTS_COUNT"]) + 2))
for name in ("nodemanager.service", "weblogic.service"):
    source = Path(e["SUITE_HOME"]) / "systemd" / (name + ".in")
    target = Path(e["STATE_HOME"]) / "units" / name
    target.write_text(Template(source.read_text()).substitute(e))
    target.chmod(0o600)
PY
log "JVM policy, Node Manager settings, and systemd units generated"
