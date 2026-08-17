#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

load_env_file() {
  local env_file="$1"
  if [[ -f "${env_file}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${env_file}"
    set +a
  fi
}

load_env_file "${PROJECT_DIR}/backend/.env"

APP_NAME="${APP_NAME:-home-flow}"
DB_PATH="${HOME_FLOW_DB_PATH:-${PROJECT_DIR}/data/storage/home_flow.db}"
BACKUP_DIR="${HOME_FLOW_BACKUP_DIR:-${PROJECT_DIR}/data/backups/db}"
RETENTION_DAYS="${HOME_FLOW_BACKUP_RETENTION_DAYS:-90}"
LOG_DIR="${HOME_FLOW_BACKUP_LOG_DIR:-${PROJECT_DIR}/tmp/logs}"
LOCK_FILE="${HOME_FLOW_BACKUP_LOCK_FILE:-/tmp/home-flow-db-backup.lock}"

usage() {
  cat <<EOF
Usage:
  $0 run            Run database backup now
  $0 install-cron   Install cron job: every Monday at 01:00
  $0 list           List recent backup files

Environment variables:
  HOME_FLOW_DB_PATH                 Default: ${PROJECT_DIR}/data/storage/home_flow.db
  HOME_FLOW_BACKUP_DIR              Default: ${PROJECT_DIR}/data/backups/db
  HOME_FLOW_BACKUP_RETENTION_DAYS   Default: 90
  HOME_FLOW_BACKUP_LOG_DIR          Default: ${PROJECT_DIR}/tmp/logs
EOF
}

log() {
  mkdir -p "${LOG_DIR}"
  echo "[$(date '+%F %T')] $*" | tee -a "${LOG_DIR}/db-backup.log"
}

run_backup() {
  mkdir -p "${BACKUP_DIR}" "${LOG_DIR}"

  if [[ ! -f "${DB_PATH}" ]]; then
    log "ERROR: database file not found: ${DB_PATH}"
    exit 1
  fi

  local timestamp
  timestamp="$(date '+%Y%m%d_%H%M%S')"
  local backup_file="${BACKUP_DIR}/${APP_NAME}_${timestamp}.db"
  local archive_file="${backup_file}.gz"
  local python_bin

  (
    flock -n 9 || {
      log "Another backup is running, skip."
      exit 0
    }

    if command -v python3 >/dev/null 2>&1; then
      python_bin="python3"
    elif command -v python >/dev/null 2>&1; then
      python_bin="python"
    else
      log "ERROR: python3 or python is required for SQLite backup."
      exit 1
    fi

    SRC_DB="${DB_PATH}" DST_DB="${backup_file}" "${python_bin}" <<'PY'
import os
import sqlite3

src_path = os.environ["SRC_DB"]
dst_path = os.environ["DST_DB"]

source = sqlite3.connect(src_path)
try:
    target = sqlite3.connect(dst_path)
    try:
        source.backup(target)
    finally:
        target.close()
finally:
    source.close()
PY

    gzip -f "${backup_file}"
    log "Backup created: ${archive_file}"

    find "${BACKUP_DIR}" -type f -name "${APP_NAME}_*.db.gz" -mtime "+${RETENTION_DAYS}" -delete
    log "Retention cleanup done: keep ${RETENTION_DAYS} days"
  ) 9>"${LOCK_FILE}"
}

install_cron() {
  mkdir -p "${LOG_DIR}"
  if ! command -v crontab >/dev/null 2>&1; then
    log "ERROR: crontab command not found. Install cron first, for example: dnf install -y cronie"
    exit 1
  fi
  local cron_cmd="0 1 * * 1 ${SCRIPT_DIR}/weekly-db-backup.sh run >> ${LOG_DIR}/db-backup.cron.log 2>&1"
  local marker="# ${APP_NAME} weekly sqlite backup"
  local tmp_file
  tmp_file="$(mktemp)"

  crontab -l 2>/dev/null | grep -vF "${marker}" | grep -vF "${SCRIPT_DIR}/weekly-db-backup.sh run" > "${tmp_file}" || true
  {
    cat "${tmp_file}"
    echo "${marker}"
    echo "${cron_cmd}"
  } | crontab -
  rm -f "${tmp_file}"

  log "Cron installed: ${cron_cmd}"
}

list_backups() {
  mkdir -p "${BACKUP_DIR}"
  ls -lh "${BACKUP_DIR}"/*.db.gz 2>/dev/null | tail -20 || true
}

main() {
  local command="${1:-run}"
  case "${command}" in
    run)
      run_backup
      ;;
    install-cron)
      install_cron
      ;;
    list)
      list_backups
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"
