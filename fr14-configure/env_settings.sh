#!/usr/bin/env bash
# Edit this file before configuration. Use the existing installation owner.
export SUITE_HOME
SUITE_HOME="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
export ORACLE_USER=oracle ORACLE_GROUP=oinstall
export ORACLE_HOME=/u01/app/oracle/product/fr14
export MW_HOME="$ORACLE_HOME"
export JAVA_HOME=/u01/app/java/jdk-17
export DOMAIN_NAME=fr14_domain
export DOMAIN_HOME="/u02/domains/$DOMAIN_NAME"
export APPLICATION_HOME="/u02/applications/$DOMAIN_NAME"
export STATE_HOME="/u02/provisioning/$DOMAIN_NAME"
export LOG_HOME="/u02/logs/$DOMAIN_NAME"
export LISTEN_ADDRESS=fr01.example.com
export MACHINE_NAME=fr14_machine
export TEMPLATE_VERSION=14.1.2.0.0 FORMS_TEMPLATE='Oracle Forms'
export FORMS_SERVER_GROUP=FORMS-MAN-SVR REPORTS_SERVER_GROUP=REPORTS-APP-SERVERS
# Existing repository PDB service and prefix. RCU is never executed by this suite.
export DB_JDBC_URL='jdbc:oracle:thin:@//db.example.com:1521/frpdb.example.com'
export RCU_PREFIX=FR14
export SECRET_HOME="$STATE_HOME/secrets"
export ADMIN_PASSWORD_FILE="$SECRET_HOME/admin.password"
export NM_PASSWORD_FILE="$SECRET_HOME/nm.password"
export SCHEMA_PASSWORD_FILE="$SECRET_HOME/schema.password"
export ADMIN_USER=weblogic NM_USER=nodemanager
export ADMIN_ADDRESS=127.0.0.1 ADMIN_PORT=7001
export ADMIN_URL="t3://$ADMIN_ADDRESS:$ADMIN_PORT"
export NM_ADDRESS=127.0.0.1 NM_PORT=5556
export FORMS_CLUSTER=forms_cluster REPORTS_CLUSTER=reports_cluster
export FORMS_COUNT=1 REPORTS_COUNT=1
export FORMS_PORT_BASE=9001 REPORTS_PORT_BASE=9101
export REPORTS_TOOLS_NAME=reptools1 REPORTS_SERVER_PREFIX=repsvr
# Set true only when colocated OHS binaries are already installed.
export OHS_ENABLED=false
export OHS_NAME=ohs1 OHS_PORT=7777 OHS_SSL_PORT=4443 OHS_ADMIN_PORT=9999
export ADMIN_XMS=1024 ADMIN_XMX=2048
export FORMS_XMS=512 FORMS_XMX=1024
export REPORTS_XMS=1024 REPORTS_XMX=2048
export JVM_COMMON='-XX:+UseG1GC -XX:+HeapDumpOnOutOfMemoryError -XX:+ExitOnOutOfMemoryError'
export REPORTS_MIN_ENGINE=1 REPORTS_INIT_ENGINE=1 REPORTS_MAX_ENGINE=4
export REPORTS_ENG_LIFE=50 REPORTS_MAX_IDLE=15
export REPORTS_ENGINE_JVM='-Xms256m -Xmx1024m'
export NOFILE_LIMIT=65536 NPROC_LIMIT=16384 TASKS_LIMIT=32768
export START_TIMEOUT=2400 STOP_TIMEOUT=300
export PATH="$JAVA_HOME/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LANG=C.UTF-8 LC_ALL=C.UTF-8
