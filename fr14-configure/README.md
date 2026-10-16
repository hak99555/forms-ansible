# Oracle Forms / Reports 14c configuration with Bash and WLST

Standalone configuration after Infrastructure/Forms/Reports **14.1.2.0.0** binary installation and RCU schema creation. No configuration manager, playbooks, inventory, or Vault is required. RCU and binary installers are not executed.

`config.sh` does not support silent configuration in this release. This bundle uses Oracle's offline WLST template APIs to create a domain, then online WLST to provision Reports Tools and native Reports Servers. References: [Forms installation guide](https://docs.oracle.com/en/middleware/developer-tools/forms/14.1.2/install-fnr/installing-oracle-forms.pdf), [Configuration Wizard overview](https://docs.oracle.com/en/middleware/fusion-middleware/14.1.2/wldcw/introduction.html), and [product templates](https://docs.oracle.com/en/middleware/fusion-middleware/14.1.2/wldtr/fusion-middleware-product-templates.html).

## Prerequisites

Linux with Bash, systemd, util-linux (`flock`, `runuser`), Python 3 plus `lxml`, and an installed certified Oracle JDK. Use the OS user that installed Oracle. OS packages, limits, storage, DNS, repository connectivity and Oracle certification must already be prepared. The selected RCU prefix must contain the needed schemas and must not belong to another domain. This implementation expects a common password for its repository schemas.

The default topology is one Forms Managed Server, one Reports Managed Server, one native Reports Server and one Reports Tools instance. Each product has a local cluster; counts can be increased before initial configuration. OHS is optional and defaults to disabled. This is one local domain, not a distributed domain deployment. It does not install TLS certificates or deploy your business application.

## 1. Stage and configure

Extract the bundle to a permanent path such as `/opt/fr14-configure`, readable by the Oracle owner. Keep the scripts there: systemd uses this path. Edit **env_settings.sh** for Oracle/JDK paths, host, existing RCU prefix and JDBC URL, domain paths, ports, counts, memory and engine settings. Domain home must not already exist. Confirm template names and server groups against your installed distribution. Management listeners are restricted to loopback.

The parent locations for the domain, application, state and log directories must be writable by the Oracle owner. For the default paths, an administrator can prepare them once:

```bash
sudo install -d -o oracle -g oinstall -m 0700 \
  /u02/domains /u02/applications /u02/provisioning /u02/logs
```

Use your actual account/group and storage paths.

## 2. Provide password files

As the Oracle owner, from the bundle directory:

```bash
source ./env_settings.sh
umask 077
mkdir -p "$SECRET_HOME"
for item in admin nm schema; do
  read -r -s -p "Password for $item: " value
  printf '\n'
  printf '%s\n' "$value" > "$SECRET_HOME/$item.password"
  chmod 600 "$SECRET_HOME/$item.password"
done
unset value
```

`schema.password` is the existing RCU schema password. `admin.password` and `nm.password` define the domain administrator and Node Manager passwords. Meet Oracle password rules. No SYS password is required. For fully unattended execution, have your secret manager provision these three private files beforehand; the scripts do not prompt. Never run the scripts with shell tracing enabled.

## 3. Configure the domain

As the Oracle owner:

```bash
bash /opt/fr14-configure/configure.sh
```

This checks installed files, validates protected credentials, loads Forms/Reports templates and dependencies, retrieves repository settings through `<PREFIX>_STB`, configures JDBC passwords, AdminServer, machine, Node Manager, clusters and Managed Servers, writes the domain, and generates memory settings and systemd units. OHS is included only when enabled.

## 4. Install services and finish online provisioning

As an administrator:

```bash
sudo bash /opt/fr14-configure/install_services.sh
```

This installs generated `nodemanager.service` and `weblogic.service`, enables startup at boot, starts Node Manager and AdminServer, provisions Reports components (and optional OHS), tunes Reports engine pools and servlet routing, starts the remaining servers, and verifies process states. It rejects preexisting service units with different content; reconcile existing services before use. Run on a host dedicated to these service names.

## Operations and recovery

```bash
sudo systemctl status nodemanager weblogic
sudo journalctl -u nodemanager -u weblogic
# As the Oracle owner:
bash /opt/fr14-configure/service.sh check
```

Drain application traffic before maintenance. Stop `weblogic` before `nodemanager`; start them in the reverse order. Lifecycle shutdown requests are graceful, subject to configured systemd timeouts.

Logs are under LOG_HOME, domain server logs and journald. Runtime Admin/NM password files must remain private and available. Initially written boot identities contain protected cleartext credentials; WebLogic encrypts them on first use. Protect the domain encryption keys and backups.

Completed domain creation can be rerun with identical settings. A hash of env_settings.sh prevents silent topology changes. An existing unmanaged domain or interrupted domain creation is rejected. Inspect logs and reconcile partial state before retrying; do not remove checkpoints just to force progress. This is provisioning, not an upgrade or password-rotation engine. Secret values are excluded from the settings hash; replacing a file does not rotate the corresponding Oracle credential.

Source validation is provided in `validate_sources.py` (Python 3.12, using its Python 2 grammar converter for WLST sources). All five source/safety tests and shell syntax checks passed in the development workspace. Oracle/WLST execution and Linux service startup have not been tested here. Runtime testing requires your installed Oracle environment. Process checks do not substitute for a successful Forms session and report execution.
