#!/usr/bin/env python3
import glob
import os
import shutil
import sys
import tempfile
from pathlib import Path
from lxml import etree
E = os.environ
DOMAIN = Path(E["DOMAIN_HOME"])

def atomic_write(path, data):
    path = Path(path)
    if path.exists():
        backup = path.with_name(path.name + ".pre-fr14")
        if not backup.exists():
            shutil.copy2(path, backup)
    fd, temp = tempfile.mkstemp(prefix=".fr14-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def parse(path):
    return etree.parse(str(path), etree.XMLParser(
        remove_blank_text=False, resolve_entities=False, load_dtd=False, no_network=True))

def save_xml(path, tree):
    atomic_write(path, etree.tostring(tree, encoding="UTF-8", xml_declaration=True))

def element(root, name):
    found = root.xpath("./*[local-name()=$name]", name=name)
    if found:
        return found[0]
    namespace = etree.QName(root).namespace
    return etree.SubElement(root, "{%s}%s" % (namespace, name) if namespace else name)

for index in range(1, int(E["REPORTS_COUNT"]) + 1):
    server = E["REPORTS_SERVER_PREFIX"] + str(index)
    path = DOMAIN / "config/fmwconfig/components/ReportsServerComponent" / server / "rwserver.conf"
    if not path.is_file():
        raise RuntimeError("Reports Server configuration missing: " + str(path))
    tree = parse(path)
    engines = tree.xpath("//*[local-name()='engine' and @id='rwEng']")
    if len(engines) != 1:
        raise RuntimeError("Expected exactly one rwEng engine in " + str(path))
    engine = engines[0]
    for attribute, setting in (
        ("minEngine", "REPORTS_MIN_ENGINE"), ("initEngine", "REPORTS_INIT_ENGINE"),
        ("maxEngine", "REPORTS_MAX_ENGINE"), ("engLife", "REPORTS_ENG_LIFE"),
        ("maxIdle", "REPORTS_MAX_IDLE")
    ):
        engine.set(attribute, E[setting])
    engine.set("jvmOptions", E["REPORTS_ENGINE_JVM"])
    save_xml(path, tree)
    pattern = str(DOMAIN / "config/fmwconfig/servers" / ("WLS_REPORTS" + str(index)) /
                  "applications/reports*/configuration/rwservlet.properties")
    servlet_paths = glob.glob(pattern)
    if not servlet_paths:
        raise RuntimeError("Reports servlet configuration missing: " + pattern)
    for servlet_path in servlet_paths:
        servlet_tree = parse(servlet_path)
        root = servlet_tree.getroot()
        element(root, "server").text = server
        element(root, "inprocess").text = "no"
        save_xml(servlet_path, servlet_tree)

if E["OHS_ENABLED"] != "true":
    print("Reports engine pools and servlet routing configured")
    sys.exit(0)

forms_backends = ",".join("%s:%d" % (E["LISTEN_ADDRESS"], int(E["FORMS_PORT_BASE"]) + i)
                         for i in range(int(E["FORMS_COUNT"])))
reports_backends = ",".join("%s:%d" % (E["LISTEN_ADDRESS"], int(E["REPORTS_PORT_BASE"]) + i)
                           for i in range(int(E["REPORTS_COUNT"])))
proxy_config = """
# Generated from env_settings.sh. Stock OHS must load mod_wl_ohs.
<Location /forms>
    SetHandler weblogic-handler
    WebLogicCluster {forms}
    DynamicServerList ON
    WLIOTimeoutSecs 300
</Location>
<Location /reports>
    SetHandler weblogic-handler
    WebLogicCluster {reports}
    DynamicServerList ON
    WLIOTimeoutSecs 300
</Location>
""".format(forms=forms_backends, reports=reports_backends).encode("utf-8")
ohs_base = DOMAIN / "config/fmwconfig/components/OHS"
master, runtime = ohs_base / E["OHS_NAME"], ohs_base / "instances" / E["OHS_NAME"]
if not master.is_dir():
    raise RuntimeError("OHS master configuration missing")
for directory in (master, runtime):
    if not directory.is_dir():
        continue
    httpd = directory / "httpd.conf"
    if not httpd.is_file():
        raise RuntimeError("OHS httpd.conf missing: " + str(httpd))
    text = httpd.read_text()
    marker = "# FR14 APPLICATION ROUTES"
    # Relative includes resolve against OHS ServerRoot in the runtime copy.
    include = 'Include "fr14-routes.conf"\n'
    if marker not in text:
        text += "\n" + marker + "\n" + include
        atomic_write(httpd, text.encode("utf-8"))
    atomic_write(directory / "fr14-routes.conf", proxy_config)
print("Reports engine pools, servlet routing, and OHS routes configured")
