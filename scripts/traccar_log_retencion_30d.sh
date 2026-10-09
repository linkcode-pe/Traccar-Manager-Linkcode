#!/bin/bash
set -euo pipefail

LOGDIR="/opt/traccar/logs"
RETENCION_DIAS=30
LOCKFILE="/run/traccar-log-retencion-30d.lock"
STATUSDIR="/var/lib/traccar-log-retencion-30d"
STATUSFILE="$STATUSDIR/status"

START="$(date '+%Y-%m-%d %H:%M:%S')"
CUTOFF="$(date -d "$RETENCION_DIAS days ago" '+%Y-%m-%d %H:%M:%S')"

mkdir -p "$STATUSDIR"
chown root:www-data "$STATUSDIR"
chmod 750 "$STATUSDIR"

write_status() {
    local RESULT="$1"
    local DELETED="$2"
    local BYTES="$3"
    local MESSAGE="$4"
    local END
    local TMP

    END="$(date '+%Y-%m-%d %H:%M:%S')"
    TMP="$STATUSFILE.tmp.$$"

    {
        printf 'last_start=%s\n' "$START"
        printf 'last_end=%s\n' "$END"
        printf 'last_result=%s\n' "$RESULT"
        printf 'last_deleted=%s\n' "$DELETED"
        printf 'last_bytes=%s\n' "$BYTES"
        printf 'last_cutoff=%s\n' "$CUTOFF"
        printf 'last_message=%s\n' "$MESSAGE"
        printf 'last_update=%s\n' "$END"
    } > "$TMP"

    chown root:www-data "$TMP"
    chmod 640 "$TMP"
    mv -f -- "$TMP" "$STATUSFILE"
}

exec 9>"$LOCKFILE"

if ! flock -n 9; then
    write_status \
        "locked" \
        "0" \
        "0" \
        "Otra ejecución ya estaba en curso; no se realizó ninguna limpieza."
    exit 0
fi

CANDIDATES=()

while IFS= read -r -d '' FILE; do
    BASENAME="${FILE##*/}"

    if [[ "$BASENAME" =~ ^tracker-server\.log\.[0-9]{8}$ ]]; then
        CANDIDATES+=("$FILE")
    fi
done < <(
    find "$LOGDIR" \
        -maxdepth 1 \
        -type f \
        -name 'tracker-server.log.????????' \
        ! -newermt "$CUTOFF" \
        -print0
)

COUNT="${#CANDIDATES[@]}"
BYTES=0

for FILE in "${CANDIDATES[@]}"; do
    SIZE="$(stat -c '%s' -- "$FILE")"
    BYTES=$((BYTES + SIZE))
done

echo "===== RETENCIÓN LOGS TRACCAR 30D ====="
echo "Inicio: $START"
echo "Corte: $CUTOFF"
echo "Candidatos: $COUNT"
echo "Bytes candidatos: $BYTES"

if [ "$COUNT" -eq 0 ]; then
    write_status \
        "completed" \
        "0" \
        "0" \
        "No había logs históricos mayores de 30 días."
    echo "No había archivos para eliminar."
    exit 0
fi

DELETED=0
DELETED_BYTES=0

for FILE in "${CANDIDATES[@]}"; do

    BASENAME="${FILE##*/}"

    if [[ ! "$BASENAME" =~ ^tracker-server\.log\.[0-9]{8}$ ]]; then
        write_status \
            "error" \
            "$DELETED" \
            "$DELETED_BYTES" \
            "Se detectó un nombre fuera del patrón permitido."
        exit 1
    fi

    if [[ "$FILE" == "$LOGDIR/tracker-server.log" ]]; then
        write_status \
            "error" \
            "$DELETED" \
            "$DELETED_BYTES" \
            "Protección activada: se intentó seleccionar el log activo."
        exit 1
    fi

    if [ ! -f "$FILE" ]; then
        continue
    fi

    SIZE="$(stat -c '%s' -- "$FILE")"

    rm -- "$FILE"

    DELETED=$((DELETED + 1))
    DELETED_BYTES=$((DELETED_BYTES + SIZE))

done

write_status \
    "completed" \
    "$DELETED" \
    "$DELETED_BYTES" \
    "Limpieza de logs históricos completada correctamente."

echo "Eliminados: $DELETED"
echo "Bytes eliminados: $DELETED_BYTES"
echo "===== FIN ====="
