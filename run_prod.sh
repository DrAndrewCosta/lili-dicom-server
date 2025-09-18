#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

export AE_TITLE="${AE_TITLE:-PACSANDREW}"
export DICOM_PORT="${DICOM_PORT:-11112}"
export WEB_PORT="${WEB_PORT:-8080}"
export STORE_DIR="${STORE_DIR:-$PROJECT_DIR/app/storage}"
export BRAND_TITLE="${BRAND_TITLE:-LILI DICOM}"
export BRAND_COLOR="${BRAND_COLOR:-#255375}"
export BASIC_AUTH_USER="${BASIC_AUTH_USER:-admin}"
export BASIC_AUTH_PASS="${BASIC_AUTH_PASS:-admin}"
export PRINT_DIRECT="${PRINT_DIRECT:-1}"
export PRINTER_NAME="${PRINTER_NAME:-}"
export ALLOW_IPS="${ALLOW_IPS:-127.0.0.1,::1}"

mkdir -p "$STORE_DIR"

python app/dicom_server.py
