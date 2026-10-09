#!/bin/bash

set -u

LOCKFILE="/run/traccar-retencion-90d.lock"

exec 9>"$LOCKFILE"

if ! flock -n 9; then
    echo "Ya existe otra ejecucion de traccar_retencion_90d.sh. No se inicia una segunda instancia."
    exit 0
fi

LIMITE_SEGUNDOS=300
LOTE=50000
PAUSA=3

STATE_DIR="/var/lib/traccar-retencion-90d"
STATUS_FILE="${STATE_DIR}/status"
state_now() { date '+%Y-%m-%dT%H:%M:%S%z'; }
write_state() {
    local tmp="${STATUS_FILE}.tmp.$$"
    if ! (
        umask 077
        {
            printf 'last_start=%s\n' "$STATE_START"
            printf 'last_end=%s\n' "$STATE_END"
            printf 'last_result=%s\n' "$STATE_RESULT"
            printf 'last_device=%s\n' "$STATE_DEVICE"
            printf 'last_remaining=%s\n' "$STATE_REMAINING"
            printf 'last_message=%s\n' "$STATE_MESSAGE"
            printf 'last_update=%s\n' "$STATE_UPDATE"
        } > "$tmp" &&
        chown root:www-data "$tmp" && chmod 640 "$tmp" && mv -f -- "$tmp" "$STATUS_FILE"
    ); then rm -f -- "$tmp"; return 1; fi
}
finish_state() {
    STATE_RESULT="$1"; STATE_MESSAGE="$2"
    STATE_END=$(state_now); STATE_UPDATE="$STATE_END"
    write_state || true
}
INICIO=$(date +%s)
STATE_START=$(state_now)
STATE_END=""
STATE_RESULT="running"
STATE_DEVICE=""
STATE_REMAINING=""
STATE_MESSAGE=""
STATE_UPDATE="$STATE_START"
write_state || true

echo "=========================================="
echo " TRACCAR - RETENCION DE 90 DIAS"
echo "=========================================="
echo "Inicio: $(date)"
echo "Limite de ejecucion: ${LIMITE_SEGUNDOS}s"
echo "Lote maximo: ${LOTE}"
echo "Retencion: 90 dias"
echo

if ! IDS=$(sudo mysql -N -e "
USE plataforma;
SELECT DISTINCT deviceid
FROM tc_positions
ORDER BY deviceid;
"); then
    echo "ERROR: no se pudo obtener la lista de dispositivos."
    finish_state error error
    exit 1
fi

for id in $IDS; do

    AHORA=$(date +%s)
    TRANSCURRIDO=$((AHORA - INICIO))

    if [ "$TRANSCURRIDO" -ge "$LIMITE_SEGUNDOS" ]; then
        echo "Limite de tiempo alcanzado. Deteniendo ejecucion."
        finish_state time_limit time_limit
        exit 0
    fi

    STATE_DEVICE="$id"
    STATE_REMAINING=""
    STATE_MESSAGE="processing_device"
    STATE_UPDATE=$(state_now)
    write_state || true

    while true; do

        AHORA=$(date +%s)
        TRANSCURRIDO=$((AHORA - INICIO))

        if [ "$TRANSCURRIDO" -ge "$LIMITE_SEGUNDOS" ]; then
            echo "Limite de tiempo alcanzado durante dispositivo $id."
            finish_state time_limit time_limit
            exit 0
        fi

        echo "Procesando dispositivo $id..."

        if ! sudo mysql -e "
USE plataforma;

DELETE FROM tc_positions
WHERE deviceid=$id
  AND fixtime < DATE_SUB(NOW(), INTERVAL 90 DAY)
  AND id NOT IN (
      SELECT positionid
      FROM tc_devices
      WHERE positionid IS NOT NULL
  )
LIMIT $LOTE;
"; then
            echo "ERROR: fallo el DELETE del dispositivo $id."
            finish_state error error
            echo "Deteniendo ejecucion por seguridad."
            exit 1
        fi

        if ! RESTANTES=$(sudo mysql -N -e "
USE plataforma;

SELECT COUNT(*)
FROM tc_positions
WHERE deviceid=$id
  AND fixtime < DATE_SUB(NOW(), INTERVAL 90 DAY)
  AND id NOT IN (
      SELECT positionid
      FROM tc_devices
      WHERE positionid IS NOT NULL
  );
"); then
            echo "ERROR: fallo la consulta de registros restantes."
            finish_state error error
            echo "Deteniendo ejecucion por seguridad."
            exit 1
        fi

        echo "Dispositivo $id: $RESTANTES registros antiguos restantes."
        STATE_DEVICE="$id"
        STATE_REMAINING="$RESTANTES"
        STATE_MESSAGE="processing_device"
        STATE_UPDATE=$(state_now)
        write_state || true

        if [ "$RESTANTES" -eq 0 ]; then
            break
        fi

        sleep "$PAUSA"

    done
done

echo
echo "=========================================="
echo " Proceso finalizado: $(date)"
finish_state completed completed
echo "=========================================="

exit 0
