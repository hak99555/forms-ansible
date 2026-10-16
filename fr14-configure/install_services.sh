#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
[[ "$(id -u)" == 0 ]] || die "Run as root"
validate_config
[[ -f "$STATE_HOME/domain.complete" ]] || die "Run configure.sh as the Oracle owner first"
exec 9>"$STATE_HOME/provision.lock"
flock -n 9 || die "Another provisioning operation is running"
# Inspect all destinations before installing either unit.
for unit in nodemanager.service weblogic.service; do
  source_unit="$STATE_HOME/units/$unit"
  [[ -f "$source_unit" ]] || die "Missing generated unit: $source_unit"
  destination="/etc/systemd/system/$unit"
  existing="$(systemctl show "$unit" --property=FragmentPath --value)"
  if [[ -n "$existing" && -f "$existing" ]]; then
    cmp -s "$existing" "$source_unit" || die "Existing service differs: $existing; reconcile before installation"
  fi
  if [[ -e "$destination" ]]; then
    cmp -s "$destination" "$source_unit" || die "Refusing to replace $destination"
  fi
done
for unit in nodemanager.service weblogic.service; do
  install -o root -g root -m 0644 "$STATE_HOME/units/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now nodemanager.service
systemctl enable --now weblogic.service
runuser -u "$ORACLE_USER" -- /bin/bash "$SUITE_HOME/service.sh" check
log "Configuration and startup completed"
