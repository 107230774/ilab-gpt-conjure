#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-}"
if [[ -z "${ROOT}" ]]; then
  echo "usage: $0 /absolute/path/to/ilab-data-root" >&2
  echo "example: $0 /opt/yuanshu-image-playground/output" >&2
  exit 2
fi

if [[ ! -d "${ROOT}" ]]; then
  echo "data root does not exist: ${ROOT}" >&2
  exit 1
fi

INPUT_ROOT="${ROOT}/webui-inputs"
OUTPUT_ROOT="${ROOT}/webui-outputs"
SOURCE_DATA_ROOT="${OUTPUT_ROOT}/source-data"

echo "This will clear Yuanshu image task history under:"
echo "  ${OUTPUT_ROOT}"
echo "  ${INPUT_ROOT}/reference-assets"
echo "  ${SOURCE_DATA_ROOT}/webui.db"
echo "It will not delete the public gallery under ${INPUT_ROOT}/gallery."
read -r -p "Type CLEAR to continue: " CONFIRM
if [[ "${CONFIRM}" != "CLEAR" ]]; then
  echo "aborted"
  exit 1
fi

find "${OUTPUT_ROOT}" -mindepth 1 -maxdepth 1 \
  ! -name source-data \
  -exec rm -rf {} +

rm -rf "${INPUT_ROOT}/reference-assets"
mkdir -p "${INPUT_ROOT}/reference-assets"

rm -f "${SOURCE_DATA_ROOT}/webui.db" "${SOURCE_DATA_ROOT}/webui.db-shm" "${SOURCE_DATA_ROOT}/webui.db-wal" "${SOURCE_DATA_ROOT}/webui-queue.json"

echo "Yuanshu image task history cleared."
