#!/usr/bin/env bash
set -euo pipefail
export AE_TITLE="${AE_TITLE:-PACSANDREW}"
export DICOM_PORT="${DICOM_PORT:-11112}"
export WEB_PORT="${WEB_PORT:-8080}"
export STORE_DIR="${STORE_DIR:-./storage}"
export BRAND_TITLE="${BRAND_TITLE:-LILI DICOM}"
export BRAND_COLOR="${BRAND_COLOR:-#255375}"
# Defaults requested: admin/admin and print-direct ON
export BASIC_AUTH_USER="${BASIC_AUTH_USER:-admin}"
export BASIC_AUTH_PASS="${BASIC_AUTH_PASS:-admin}"
export PRINT_DIRECT="${PRINT_DIRECT:-1}"
export PRINTER_NAME="${PRINTER_NAME:-}"
export ALLOW_IPS="${ALLOW_IPS:-127.0.0.1,::1}"
mkdir -p logs
exec python -m gunicorn -c gunicorn.conf.py wsgi:app
