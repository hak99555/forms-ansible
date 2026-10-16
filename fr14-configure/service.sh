#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
require_oracle
validate_config
case "${1:-}" in
  nodemanager) log "Starting per-domain Node Manager"; exec "$DOMAIN_HOME/bin/startNodeManager.sh" ;;
  admin) export SERVER_NAME=AdminServer; log "Starting AdminServer"; exec "$DOMAIN_HOME/bin/startWebLogic.sh" ;;
  start|stop|check)
    exec "$ORACLE_HOME/oracle_common/common/bin/wlst.sh" "$SUITE_HOME/lifecycle.py" "$1" ;;
  *) die "Usage: $0 nodemanager|admin|start|stop|check" ;;
esac
