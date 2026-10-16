#!/usr/bin/env bash
source "$(dirname -- "$0")/common.sh"
init_job
for command in python3 flock tee; do command -v "$command" >/dev/null || die "Missing $command"; done
[[ -x "$JAVA_HOME/bin/java" ]] || die "JAVA_HOME must point to the installed certified JDK"
[[ -x "$ORACLE_HOME/oracle_common/common/bin/wlst.sh" ]] || die "WLST is missing or not executable"
python3 -c 'import lxml.etree' || die "Install the OS python3-lxml package"
"$JAVA_HOME/bin/java" -version
templates=(
  forms/common/templates/wls/forms_template.jar
  reports/common/templates/wls/oracle.reports_app_template.jar
  ReportsToolsComponent/common/templates/wls/oracle.reports_tools_template.jar
  ReportsServerComponent/common/templates/wls/oracle.reports_server_template.jar
)
if [[ "$OHS_ENABLED" == true ]]; then templates+=(ohs/common/templates/wls/ohs_managed_template.jar); fi
for template in "${templates[@]}"; do
  [[ -r "$ORACLE_HOME/$template" ]] || die "Missing template: $template"
done
for password_file in "$ADMIN_PASSWORD_FILE" "$NM_PASSWORD_FILE" "$SCHEMA_PASSWORD_FILE"; do
  secret "$password_file" >/dev/null
done
# Freeze all configuration inputs. Operational secret values are intentionally excluded.
identity="$(sha256sum "$SUITE_HOME/env_settings.sh" | cut -d ' ' -f 1)"
if [[ -e "$STATE_HOME/domain.complete" && ! -f "$STATE_HOME/configuration.identity" ]]; then
  die "Completed domain has no configuration identity; reconcile its ownership before continuing"
fi
if [[ -e "$STATE_HOME/configuration.identity" ]]; then
  [[ "$(cat "$STATE_HOME/configuration.identity")" == "$identity" ]] || die "Settings changed; use a planned maintenance procedure"
fi
if [[ -e "$STATE_HOME/domain.started" && ! -e "$STATE_HOME/domain.complete" ]]; then
  die "Previous domain creation did not finish; inspect logs and domain before retrying"
fi
if [[ ! -e "$STATE_HOME/domain.complete" ]]; then
  [[ ! -e "$DOMAIN_HOME" ]] || die "Refusing to overwrite an existing domain"
  mkdir -p "$(dirname -- "$DOMAIN_HOME")" "$APPLICATION_HOME"
  printf '%s\n' "$identity" > "$STATE_HOME/configuration.identity"
  printf '%s\n' "$DOMAIN_NAME" > "$STATE_HOME/domain.started"
fi
"$ORACLE_HOME/oracle_common/common/bin/wlst.sh" "$SUITE_HOME/04_configure_domain.py"
rm -f -- "$STATE_HOME/domain.started"
# Run in this shell so the provisioning lock remains held without reacquiring it.
FR14_CONFIGURE_ACTIVE=1
source "$SUITE_HOME/05_post_config.sh"
log "Domain configured. As root, run: bash $SUITE_HOME/install_services.sh"
