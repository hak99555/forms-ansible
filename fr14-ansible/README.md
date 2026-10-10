# Forms / Reports 14c deployment through Ansible

Two entry points deploy **Oracle Forms and Reports 14.1.2.0.0** on x86_64 **Oracle Linux 8.6+ or Oracle Linux 9.2+**. Ansible detects the OS version automatically; other distributions are rejected:

| Playbook | Responsibility |
| --- | --- |
| `install_middleware.yml` | OS packages, OS account, limits, directories, Oracle inventory, Oracle JDK archive installation, Infrastructure, Forms/Reports, optional separate OHS binaries |
| `configure_forms_reports.yml` | RCU schemas, production WebLogic domain, Forms/Reports clusters and Managed Servers, JVM settings, Node Manager, native Reports components, optional colocated OHS, systemd services, startup and health checks |

**All deployment tasks and generated source content are inline in the two main playbooks.** There are no roles, external task includes, controller-side template files, or separate deployment scripts. The shared parameter file, inventory and Vault inputs remain separate. Ansible's `command` module invokes the necessary Oracle silent installers, RCU and WLST without GUI steps. The configuration playbook embeds the two Jython programs, JVM override hook, systemd units and OHS routes in its `copy` tasks, then writes them to the target. Operators do not execute the generated WLST programs separately. The installation playbook embeds its installer response files and OS preparation tasks.

This is a **new-installation implementation**, with one independent domain per inventory host, and configurable local Forms and Reports clusters. It does not build one shared domain across hosts. Default: two Forms Managed Servers, two Reports Managed Servers, one native Reports Server per Reports Managed Server, one Reports Tools component, and optional OHS. Setting `fr_ohs_enabled: false` excludes the OHS template, instance, routes, startup and verification. Oracle media may still install OHS binaries as part of its distribution.

## Validation status

The included ten source/topology smoke tests passed in this workspace. They check YAML and inline Jinja parsing, embedded Python source grammar, Oracle Linux 8/9 validation, OHS on/off and multiple server counts, invalid parameter rejection, configuration identities, generated units/routes, and RCU password ordering. Additional checks confirm that both playbooks have no role/task/template-file dependencies, use identical parameter validation, and preserve the per-server Reports configuration mapping after flattening the loops. They do **not** execute Ansible or emulate Oracle.

This Windows workspace has neither a Linux Ansible controller nor Oracle installation media, target hosts or a repository database. **Ansible syntax-check and actual Oracle installation/configuration have not been executed here.** Run both syntax checks below on your Linux controller, then validate a complete deployment on a representative staging host. Confirm the exact installed template names, server-group identifiers, generated component paths, and supported package/kernel/JDK/database/patch combination against your Oracle media and certification before production use.

## 1. Prepare the controller and target

Use a Linux Ansible controller (or Linux in WSL), Python 3.12+, and an approved `ansible-core` 2.19/2.20 release. Run commands from this directory so `ansible.cfg` and inventory variables are found.

```bash
ansible-galaxy collection install -r requirements.yml
```

The target needs SSH, Python 3, sudo access for the inventory account to become root and the Oracle account, enabled approved package repositories, working DNS, mounted storage, and connectivity to an existing certified Oracle repository database/PDB. Required development/Motif packages must be available from your approved repositories. The package task fails if any are missing; it does not enable external repositories.

The playbook installs package names, rather than pinning minimum RPM versions. Validate installed versions and the running kernel against Oracle's system requirements; keep your approved OS patch baseline current. SELinux and firewalld remain in effect. Provide the site's network, DNS, time-source and SELinux policy. Management uses plain transport bound to **127.0.0.1**, with WLST executed locally on the target.

## 2. Set the parameter file

Edit **`group_vars/all/parameters.yml`**. This is the central YAML parameter file, loaded automatically for `inventory.ini`.

| Parameter family | Examples |
| --- | --- |
| OS account | `fr_os_user`, `fr_os_group`, `fr_os_home` |
| Paths | `fr_oracle_home`, `fr_java_home`, `fr_domain_home`, `fr_application_home`, `fr_stage`, `fr_state`, `fr_log_home` |
| Domain | `fr_domain_name`, `fr_machine_name`, `fr_forms_cluster`, `fr_reports_cluster` |
| Ports | `fr_admin_port`, `fr_nm_port`, `fr_forms_port_base`, `fr_reports_port_base`, OHS HTTP/SSL/admin ports |
| Managed Servers | `fr_forms_count`, `fr_reports_count`, generated name prefixes |
| JVM | Admin/Forms/Reports initial and maximum heap in MB, common and per-tier Java options |
| Reports engines | Minimum/initial/maximum engines, job-based recycling, idle limit, engine JVM options |
| OHS | `fr_ohs_enabled`, instance name, ports, server name, proxy timeout, optional separate installer |
| Repository | DB connect string and JDBC URL, admin role, schema prefix, component list, `fr_rcu_create` |
| Installation | Media location/filenames, SHA-256 hashes, JDK archive directory, installer types |
| Resources | Memory/disk thresholds, nofile/nproc/tasks limits, startup/stop/installation timeouts |

All target paths must be absolute and contain no spaces. Domain home must be outside Oracle home. Ports are checked for duplicates and must be between 1024 and 65535. Counts must be at least one for each product. Port ranges start at the configured base and increment by one.

The JDK example directory is a release-baseline example, **not a recommendation to deploy an old CPU**. Set `fr_jdk_directory`, `fr_jdk_archive` and `fr_jdk_sha256` to your current certified Oracle JDK update. The archive must expand to `fr_java_parent/fr_jdk_directory`; the playbook checks Oracle vendor metadata and the supported release baseline.

Update `inventory.ini` for SSH. For per-host settings, create `host_vars/fr01.yml` (filename equals the inventory hostname):

```yaml
fr_domain_name: finance_domain
fr_domain_home: /u02/domains/finance_domain
fr_application_home: /u02/applications/finance_domain
fr_state: /u02/provisioning/finance_domain
fr_log_home: /u02/logs/finance_domain
fr_listen_address: fr01.example.com
fr_rcu_prefix: FIN01
fr_ohs_enabled: false
fr_forms_count: 3
fr_reports_count: 2
fr_forms_port_base: 9001
fr_reports_port_base: 9101
fr_forms_xms_mb: 1024
fr_forms_xmx_mb: 2048
```

Give each independent domain a distinct RCU prefix, including hosts sharing the same database. The prefix must begin with a letter and contain at most 12 uppercase alphanumeric characters. Domain-related paths do not automatically change when only the domain name changes; configure them together as shown. You may also pass an environment override file with `-e @env.yml` to **both** playbooks.

## 3. Supply Oracle media

Obtain licensed, certified Oracle media and independently verify SHA-256 hashes. The playbook does not download from Oracle Software Delivery Cloud or MOS.

With `fr_media_location: target`, stage the following under `fr_stage` on the Linux target:

1. Oracle JDK `.tar.gz` archive.
2. FMW Infrastructure 14.1.2 installer `.jar` (full Infrastructure, not standalone WLS).
3. Complete extracted Forms and Reports native Linux installer distribution, preserving companion files beside the `.bin`.
4. A separate colocated OHS 14.1.2 native installer distribution only when your media requires it and `fr_ohs_install_separately: true`.

Use your actual media filenames; the names in the parameter file are examples. Set every required SHA-256 parameter; empty checksums deliberately fail validation. When Ansible copies media (`fr_media_location: controller`), set `fr_controller_media_dir` and list native companion filenames in `fr_media_companion_files`. Companion files are copied; the SHA-256 checks apply to the configured installer files and JDK archive. Your staged distributions must be trusted and complete.

If OHS is enabled but its runtime/template is absent after the requested installations, installation fails. Select the matching certified media and separate OHS option when appropriate. No prerequisite-ignore flags are used.

## 4. Create the Vault file

```bash
cp vault.example.yml vault.yml
chmod 600 vault.yml
# Fill in all four password values, then encrypt.
ansible-vault encrypt vault.yml
```

Secrets are `vault_fr_db_password`, `vault_fr_schema_password`, `vault_fr_admin_password`, and `vault_fr_nm_password`. Use passwords meeting Oracle policy (the procedure enforces at least 12 characters for schema/Admin/NM passwords), with no embedded newline. For `fr_rcu_create: false`, the DB administrative password is not needed; supply the existing prefix's common schema password. The domain creator retrieves repository metadata through STB.

RCU receives its administrative and ordered per-component passwords on stdin, never in command-line arguments. The configuration input JSON is private and removed in the playbook's `always` cleanup. Runtime Admin/NM credentials remain in `fr_state/secrets/runtime.json`, owned by the Oracle account with mode 0600, because systemd lifecycle operations use them. Boot identities are written with Java Properties escaping and mode 0600; WebLogic encrypts these after first use. Protect these files, the domain encryption key and backups. A killed controller or power loss can leave transient input files: inspect the private secrets directory during recovery.

## 5. Run the two playbooks

```bash
ansible-playbook install_middleware.yml --syntax-check
ansible-playbook configure_forms_reports.yml --syntax-check

ansible-playbook install_middleware.yml
ansible-playbook configure_forms_reports.yml -e @vault.yml --ask-vault-pass
```

For fully unattended runs, use an approved Vault password file or credential-provider executable:

```bash
ansible-playbook install_middleware.yml -e @env.yml
ansible-playbook configure_forms_reports.yml -e @env.yml -e @vault.yml \
  --vault-password-file /run/secrets/ansible-vault-password
```

No interactive Oracle wizard or target-side manual execution is required. Check mode is intentionally rejected: it cannot simulate repository and Oracle configuration side effects. Syntax-check remains available.

The installation playbook prepares the OS and account, verifies media, extracts and checks the JDK, installs Infrastructure followed by Forms/Reports and requested OHS, completes the inventory root script where present, and verifies expected templates.

The configuration playbook creates explicit repository components unless using an existing repository, creates the domain offline with the requested server groups/clusters, configures JVM startup hooks and per-domain Node Manager, installs systemd units, starts AdminServer and Node Manager, enrolls Node Manager, creates Reports and optional OHS components online, tunes generated files, starts all servers, and verifies runtime states and servlet HTTP responses.

## Operations and validation

For the default `fr_domain_name: fr14_domain`:

```bash
systemctl status fr14-fr14_domain-AdminServer fr14-fr14_domain-nodemanager
systemctl status fr14-fr14_domain-WLS_FORMS1 fr14-fr14_domain-WLS_REPORTS1
systemctl status fr14-fr14_domain-components
journalctl -u fr14-fr14_domain-AdminServer
```

Each configured Managed Server has a separate unit. The native component unit delegates startup to Node Manager and performs runtime checks; it is a oneshot service with `RemainAfterExit=yes`, so `active (exited)` is expected. Node Manager supervises native components; systemd supervises WebLogic JVMs. One aggregate native unit's status does not prove every native process remains healthy after startup.

Drain client traffic before maintenance. Stop the components unit, then every Managed Server unit, AdminServer and Node Manager. Start in reverse order. Units express dependency order for host shutdown and boot; test graceful shutdown with real workloads. Reaching a systemd stop timeout can terminate processes.

With OHS enabled, servlet endpoints are:

```text
http://<host>:<fr_ohs_port>/forms/frmservlet
http://<host>:<fr_ohs_port>/reports/rwservlet
```

Without OHS, use each Forms or Reports Managed Server's port directly. The OHS SSL listener uses Oracle's generated initial configuration; supplying a port does not install your trusted production certificate. Trusted TLS/wallets, external load balancers, SSO, application deployment, firewall rules and backups require the site's configuration.

Before production acceptance, verify Oracle inventory, RCU schema validity and datasource connectivity; all application targets and generated per-server configuration; real Forms sessions and representative Reports rendering; OHS routing with authentication; reboot/crash/database-outage recovery; and native/JVM memory capacity. HTTP status checks only establish servlet reachability (Reports may respond 401/403 by policy), not successful report jobs or Forms sessions.

Forms native `frmweb` memory and Reports native/engine memory are additional to Managed Server heaps. Each Reports Server has its own engine pool. `fr_reports_engine_life` counts processed jobs, not elapsed time. Size the host from realistic concurrent sessions/jobs, and manage GC logs/heap dump retention separately.

## Reruns and failure recovery

Successful installation/domain phases have identity checkpoints. Repeating the same inputs reuses these phases and ensures configured services are started. Existing unmanaged JDKs/homes/domains are rejected. Started-without-completed markers cause failure so a partial installer/RCU/domain operation cannot be blindly repeated. The two playbooks share an exclusive directory lock under `fr_state`; an interrupted process can leave a stale lock.

Never remove checkpoints or a lock to force a retry while another deployment or Oracle tool may still be running. Inspect processes, Oracle inventory, installer/RCU logs, schemas and domain files; reconcile the failed phase first. No automatic schema drop, domain deletion or rollback occurs. RCU and domain-creation output is saved privately under `fr_log_home`, including on command failure; Oracle's native installer/RCU logs and service journals provide additional diagnostics. Logs may contain sensitive operational data.

Topology and JVM parameter changes are rejected once the domain is created; these playbooks are not a live topology reconciliation or upgrade engine. Runtime Admin/NM password changes are also rejected; changing the Vault does not rotate repository or domain credentials. Plan an explicit maintenance/upgrade/credential-rotation procedure. Using different state paths to bypass ownership checks is unsupported.

## Source smoke tests

Optional controller/source validation (not required by either deployment playbook):

```bash
python -m pip install PyYAML Jinja2
python tests/validate_sources.py
```

## Oracle references

- [14c installation prerequisites](https://docs.oracle.com/en/middleware/developer-tools/forms/14.1.2/install-fnr/preparing-install.html)
- [14c silent installation and separate configuration](https://docs.oracle.com/en/middleware/developer-tools/forms/14.1.2/install-fnr/installing-oracle-forms-silent-mode.html)
- [14c product domain templates](https://docs.oracle.com/en/middleware/fusion-middleware/14.1.2/wldtr/fusion-middleware-product-templates.html)
- [14c RCU command-line interface](https://docs.oracle.com/en/middleware/fusion-middleware/14.1.2/rcuug/running-repository-creation-utility-command-line.html)
- [14c system requirements](https://docs.oracle.com/en/middleware/fusion-middleware/14.1.2/sysrs/system-requirements-and-specifications.html)
- [Oracle JDK release baselines for 14.1.2](https://blogs.oracle.com/fusionmiddlewaresupport/announcement-oracle-fmw-forms-and-reports-1412-has-been-released)
- [14c Reports documentation guidance](https://docs.oracle.com/en/middleware/developer-tools/forms/14.1.2/install-fnr/oracle-reports.html)
- [Reports component provisioning](https://docs.oracle.com/middleware/12213/formsandreports/install-fnr/installing-and-configuring-oracle-forms-and-reports1.htm)
- [14c OHS component creation](https://docs.oracle.com/en/middleware/fusion-middleware/web-tier/14.1.2/administer-ohs/getstart.html)

Oracle's 14c Reports guidance points to the 12.2.1.3 documentation for unchanged Reports functionality while requiring 14.1.2 software. This procedure does not configure a Reports Naming Service; Oracle documents it as unavailable in the initial 14.1.2 release.
