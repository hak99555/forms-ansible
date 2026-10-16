# WLST / Jython 2.7 -- invoke through oracle_common/common/bin/wlst.sh.
import os
import traceback
from java.io import FileOutputStream
from java.util import Properties
E = os.environ

def required(name):
    value = E.get(name)
    if not value:
        raise RuntimeError("Missing environment variable: " + name)
    return value

def number(name):
    return int(required(name))

def password(name):
    value = open(required(name), "rb").read().decode("utf-8").rstrip("\n")
    if not value or "\n" in value or "\r" in value:
        raise RuntimeError("Invalid secret: " + name)
    return value

def save_properties(path, values):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent, 0700)
    props = Properties()
    for key, value in values.items():
        props.setProperty(key, value)
    stream = FileOutputStream(path)
    try:
        props.store(stream, "Initial boot credentials; protect this file")
    finally:
        stream.close()
    os.chmod(path, 0600)

def configure():
    home = required("DOMAIN_HOME")
    marker = os.path.join(required("STATE_HOME"), "domain.complete")
    if os.path.exists(marker):
        if not os.path.isfile(os.path.join(home, "config", "config.xml")):
            raise RuntimeError("Checkpoint exists but config.xml is missing")
        print("Domain already created")
        return
    if os.path.exists(home):
        raise RuntimeError("Refusing to overwrite existing or partial domain")

    admin_password = password("ADMIN_PASSWORD_FILE")
    schema_password = password("SCHEMA_PASSWORD_FILE")
    nm_password = password("NM_PASSWORD_FILE")
    templates = ["Basic WebLogic Server Domain", required("FORMS_TEMPLATE"),
                     "Oracle Reports Application", "Oracle Reports Tools",
                     "Oracle Reports Server"]
    if E.get("OHS_ENABLED") == "true":
        templates.append("Oracle HTTP Server (Colocated)")
    for template in templates:
        selectTemplate(template, required("TEMPLATE_VERSION"))
    loadTemplates()

    # Resolve the security path before changing the template domain name.
    cd("/")
    template_domain = cmo.getName()
    cd("/Security/" + template_domain + "/User/weblogic")
    set("Name", required("ADMIN_USER"))
    set("Password", admin_password)
    setOption("DomainName", required("DOMAIN_NAME"))
    setOption("ServerStartMode", "prod")
    setOption("JavaHome", required("JAVA_HOME"))
    setOption("AppDir", required("APPLICATION_HOME"))
    setOption("NodeManagerType", "PerDomainNodeManager")
    setOption("OverwriteDomain", "false")
    cd("/")
    set("Name", required("DOMAIN_NAME"))
    cd("/Servers/AdminServer")
    set("ListenAddress", required("ADMIN_ADDRESS"))
    set("ListenPort", number("ADMIN_PORT"))

    cd("/")
    create(required("MACHINE_NAME"), "UnixMachine")
    cd("/Machines/" + required("MACHINE_NAME"))
    create(required("MACHINE_NAME"), "NodeManager")
    cd("/Machines/%s/NodeManager/%s" %
       (required("MACHINE_NAME"), required("MACHINE_NAME")))
    set("ListenAddress", required("NM_ADDRESS"))
    set("ListenPort", number("NM_PORT"))
    set("NMType", "Plain")
    cd("/Servers/AdminServer")
    set("Machine", required("MACHINE_NAME"))

    cd("/JDBCSystemResource/LocalSvcTblDataSource/JdbcResource/"
       "LocalSvcTblDataSource/JDBCDriverParams/NO_NAME_0")
    set("URL", required("DB_JDBC_URL"))
    set("PasswordEncrypted", schema_password)
    cd("Properties/NO_NAME_0/Property/user")
    set("Value", required("RCU_PREFIX") + "_STB")
    getDatabaseDefaults()
    cd("/JDBCSystemResource")
    datasource_names = list(ls(returnMap="true").keys())
    for name in datasource_names:
        cd("/JDBCSystemResource/%s/JdbcResource/%s/JDBCDriverParams/NO_NAME_0" % (name, name))
        set("PasswordEncrypted", schema_password)

    all_servers = ["AdminServer"]
    for component, template_server in (("FORMS", "WLS_FORMS"), ("REPORTS", "WLS_REPORTS")):
        cluster = required(component + "_CLUSTER")
        prefix = "WLS_" + component
        count = number(component + "_COUNT")
        base_port = number(component + "_PORT_BASE")
        cd("/")
        create(cluster, "Cluster")
        cd("/Clusters/" + cluster)
        set("ClusterMessagingMode", "unicast")
        set("ClusterAddress", ",".join(
            ["%s:%d" % (required("LISTEN_ADDRESS"), base_port + i) for i in range(count)]))
        cd("/Servers/" + template_server)
        set("Name", prefix + "1")
        for index in range(1, count + 1):
            name = prefix + str(index)
            if index > 1:
                cd("/")
                create(name, "Server")
            cd("/Servers/" + name)
            set("ListenAddress", required("LISTEN_ADDRESS"))
            set("ListenPort", base_port + index - 1)
            set("Machine", required("MACHINE_NAME"))
            set("Cluster", cluster)
            set("AutoRestart", "true")
            set("RestartMax", 3)
            set("RestartIntervalSeconds", 600)
            set("RestartDelaySeconds", 15)
            setServerGroups(name, [required(component + "_SERVER_GROUP")])
            all_servers.append(name)

    cd("/SecurityConfiguration/" + required("DOMAIN_NAME"))
    set("NodeManagerUsername", required("NM_USER"))
    set("NodeManagerPasswordEncrypted", nm_password)
    writeDomain(home)
    closeDomain()
    for server in all_servers:
        save_properties(os.path.join(home, "servers", server, "security", "boot.properties"),
                        {"username": required("ADMIN_USER"), "password": admin_password})
    with open(marker, "w") as stream:
        stream.write(required("DOMAIN_NAME") + "\n")
    os.chmod(marker, 0600)
    print("Domain creation completed")

try:
    configure()
except:
    traceback.print_exc()
    exit(exitcode=1)
exit(exitcode=0)
