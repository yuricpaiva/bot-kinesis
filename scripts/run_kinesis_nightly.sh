#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

mkdir -p logs

LOCK_FILE="${LOCK_FILE:-/tmp/bot-kinesis-nightly.lock}"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Outra carga noturna Kinesis ja esta em execucao. Encerrando."
  exit 0
fi

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

export SHARD_ITERATOR_TYPE="TRIM_HORIZON"
export MAX_RECORDS_PER_READ="${MAX_RECORDS_PER_READ:-1000}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
RUN_STARTED_AT="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="logs/kinesis_nightly_${RUN_STARTED_AT}.log"
PAUSE_COLLECTOR_SERVICE="${PAUSE_COLLECTOR_SERVICE:-}"
COLLECTOR_SERVICE_WAS_ACTIVE="false"

cleanup() {
  if [[ "$COLLECTOR_SERVICE_WAS_ACTIVE" == "true" && -n "$PAUSE_COLLECTOR_SERVICE" ]]; then
    systemctl start "$PAUSE_COLLECTOR_SERVICE"
  fi
}
trap cleanup EXIT

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando carga noturna Kinesis."
  echo "Projeto: $PROJECT_DIR"
  echo "SHARD_ITERATOR_TYPE=$SHARD_ITERATOR_TYPE"
  echo "MAX_RECORDS_PER_READ=$MAX_RECORDS_PER_READ"

  if [[ -n "$PAUSE_COLLECTOR_SERVICE" ]]; then
    if systemctl is-active --quiet "$PAUSE_COLLECTOR_SERVICE"; then
      COLLECTOR_SERVICE_WAS_ACTIVE="true"
      echo "Pausando servico continuo: $PAUSE_COLLECTOR_SERVICE"
      systemctl stop "$PAUSE_COLLECTOR_SERVICE"
    else
      echo "Servico continuo nao estava ativo: $PAUSE_COLLECTOR_SERVICE"
    fi
  fi

  "$PYTHON_BIN" -m src.collector_raw --until-caught-up
  "$PYTHON_BIN" -m src.processor_dw --until-empty

  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Carga noturna Kinesis finalizada."
} 2>&1 | tee -a "$LOG_FILE"
