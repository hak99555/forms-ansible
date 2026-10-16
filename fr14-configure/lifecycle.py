# WLST / Jython 2.7
import os
import sys
import time
import subprocess
import traceback
E = os.environ
ACTION = sys.argv[1]

def secret(key):
    value = open(E[key], "rb").read().decode("utf-8").rstrip("\n")
    if not value or "\n" in value or "\r" in value:
        raise RuntimeError("Invalid secret: " + key)
    return value

def managed_servers():
    return ["WLS_" + component + str(i)
            for component in ("FORMS", "REPORTS")
            for i in range(1, int(E[component + "_COUNT"]) + 1)]

def report_servers():
    return [E["REPORTS_SERVER_PREFIX"] + str(i)
            for i in range(1, int(E["REPORTS_COUNT"]) + 1)]

def native_servers():
    result = [(n, "ReportsServerComponent") for n in report_servers()]
    if E["OHS_ENABLED"] == "true":
        result.append((E["OHS_NAME"], "OHS"))
    return result

def admin_connect(wait):
    deadline = time.time() + (int(E["START_TIMEOUT"]) - 60 if wait else 30)
    while True:
        try:
            connect(E["ADMIN_USER"], secret("ADMIN_PASSWORD_FILE"),
                    E["ADMIN_URL"], timeout=10000)
            return
        except:
            if time.time() >= deadline:
                raise
            time.sleep(5)

def nm_connect():
    deadline = time.time() + 60
    while True:
        try:
            nmConnect(E["NM_USER"], secret("NM_PASSWORD_FILE"),
                      E["NM_ADDRESS"], E["NM_PORT"], E["DOMAIN_NAME"],
                      E["DOMAIN_HOME"], "plain")
            return
        except:
            if time.time() >= deadline:
                raise
            time.sleep(3)

def nm_start_checked(name, server_type):
    current = nmServerStatus(name, serverType=server_type)
    if current != "RUNNING":
        nmStart(name, serverType=server_type)
    deadline = time.time() + 300
    while time.time() < deadline:
        current = nmServerStatus(name, serverType=server_type)
        if current == "RUNNING":
            return
        if current in ("FAILED", "FAILED_NOT_RESTARTABLE"):
            raise RuntimeError("%s entered %s" % (name, current))
        time.sleep(3)
    raise RuntimeError("Timed out starting " + name)

def wait_for_weblogic(name):
    domainRuntime()
    deadline = time.time() + 300
    while time.time() < deadline:
        cd("/ServerLifeCycleRuntimes/" + name)
        current = cmo.getState()
        if current == "RUNNING":
            return
        if current in ("FAILED", "FAILED_NOT_RESTARTABLE"):
            raise RuntimeError("%s entered %s" % (name, current))
        time.sleep(3)
    raise RuntimeError("WebLogic runtime not RUNNING: " + name)

def provision_components():
    serverConfig()
    cd("/")
    if getMBean("/SystemComponents/" + E["REPORTS_TOOLS_NAME"]) is None:
        createReportsToolsInstance(instanceName=E["REPORTS_TOOLS_NAME"],
                                   machine=E["MACHINE_NAME"])
    for name in report_servers():
        serverConfig()
        if getMBean("/SystemComponents/" + name) is None:
            createReportsServerInstance(instanceName=name, machine=E["MACHINE_NAME"])
    serverConfig()
    if E["OHS_ENABLED"] == "true" and getMBean("/SystemComponents/" + E["OHS_NAME"]) is None:
        ohs_createInstance(instanceName=E["OHS_NAME"], machine=E["MACHINE_NAME"],
                           listenPort=int(E["OHS_PORT"]),
                           sslPort=int(E["OHS_SSL_PORT"]),
                           adminPort=int(E["OHS_ADMIN_PORT"]))

def check():
    for name in ["AdminServer"] + managed_servers():
        wait_for_weblogic(name)
    for name, kind in native_servers():
        current = nmServerStatus(name, serverType=kind)
        if current != "RUNNING":
            raise RuntimeError("%s is %s" % (name, current))
    print("All configured server processes are RUNNING")

def start():
    provision_components()
    marker = os.path.join(E["STATE_HOME"], "components.complete")
    # Separate tuning checkpoint avoids editing active component files after a
    # later startup failure or an AdminServer-only restart.
    tuned = os.path.join(E["STATE_HOME"], "components.tuned")
    if not os.path.exists(tuned):
        subprocess.check_call(["/usr/bin/python3", E["SUITE_HOME"] + "/tune_components.py"])
        with open(tuned, "w") as f:
            f.write("complete\n")
        os.chmod(tuned, 0600)
    for name in report_servers():
        nm_start_checked(name, "ReportsServerComponent")
    for name in managed_servers():
        nm_start_checked(name, "WebLogic")
        wait_for_weblogic(name)
    if E["OHS_ENABLED"] == "true":
        nm_start_checked(E["OHS_NAME"], "OHS")
    check()
    with open(marker, "w") as f:
        f.write("complete\n")
    os.chmod(marker, 0600)

def stop():
    failures = []
    serverConfig()
    for name, kind in (([(E["OHS_NAME"], "SystemComponent")] if E["OHS_ENABLED"] == "true" else []) +
                       [(n, "Server") for n in reversed(managed_servers())] +
                       [(n, "SystemComponent") for n in report_servers()]):
        try:
            if kind == "SystemComponent":
                serverConfig()
                if getMBean("/SystemComponents/" + name) is None:
                    continue
            else:
                domainRuntime()
                cd("/ServerLifeCycleRuntimes/" + name)
                if cmo.getState() == "SHUTDOWN":
                    continue
            shutdown(name, kind, ignoreSessions="false",
                     timeOut=int(E["STOP_TIMEOUT"]), force="false", block="true")
        except:
            failures.append(name)
            traceback.print_exc()
    if failures:
        raise RuntimeError("Graceful shutdown failed: " + ", ".join(failures))
    shutdown("AdminServer", "Server", ignoreSessions="false",
             timeOut=int(E["STOP_TIMEOUT"]), force="false", block="true")

try:
    admin_connect(ACTION == "start")
    nm_connect()
    if ACTION == "start":
        start()
    elif ACTION == "stop":
        stop()
    elif ACTION == "check":
        check()
    else:
        raise RuntimeError("Unknown lifecycle operation")
except:
    traceback.print_exc()
    exit(exitcode=1)
exit(exitcode=0)
