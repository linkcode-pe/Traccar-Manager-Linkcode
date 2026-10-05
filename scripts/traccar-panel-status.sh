#!/bin/bash
set -euo pipefail

readonly SYSTEMCTL='/usr/bin/systemctl'
readonly STATUS_DIR='/var/lib/traccar-panel-status'
readonly STATUS_FILE="${STATUS_DIR}/status"
readonly MKTEMP='/usr/bin/mktemp'
readonly CHMOD='/usr/bin/chmod'
readonly STAT='/usr/bin/stat'
readonly RM='/usr/bin/rm'
readonly MV='/usr/bin/mv'
readonly DATE='/usr/bin/date'

tmp=''
cleanup() {
    if [[ -n "$tmp" && -e "$tmp" ]]; then
        "$RM" -f -- "$tmp" || true
    fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

fail() {
    printf 'traccar-panel-status: %s\n' "$1" >&2
    exit 1
}

if ! output=$("$SYSTEMCTL" show traccar \
    -p ActiveState \
    -p SubState \
    -p ActiveEnterTimestamp \
    -p ExecMainStartTimestamp \
    -p NRestarts \
    --no-pager); then
    fail 'fallo la consulta de estado'
fi

declare -A seen=()
declare -A values=()
while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" != *$'\r'* ]] || fail 'salida con retorno de carro'
    case "$line" in
        ActiveState=*) key='ActiveState' ;;
        SubState=*) key='SubState' ;;
        ActiveEnterTimestamp=*) key='ActiveEnterTimestamp' ;;
        ExecMainStartTimestamp=*) key='ExecMainStartTimestamp' ;;
        NRestarts=*) key='NRestarts' ;;
        *) fail 'campo ausente, duplicado o inesperado en la salida' ;;
    esac
    value=${line#*=}
    [[ -z "${seen[$key]+present}" ]] || fail 'campo duplicado en la salida'
    seen[$key]=1
    [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || fail 'valor con salto de linea'
    values[$key]="$value"
done <<< "$output"

for key in ActiveState SubState ActiveEnterTimestamp ExecMainStartTimestamp NRestarts; do
    [[ -n "${seen[$key]+present}" ]] || fail 'falta un campo requerido'
done

[[ "${values[ActiveState]}" =~ ^[A-Za-z0-9_.+-]+$ ]] || fail 'ActiveState invalido'
[[ "${values[SubState]}" =~ ^[A-Za-z0-9_.+-]+$ ]] || fail 'SubState invalido'
print_re='^[[:print:]]+$'
[[ "${values[ActiveEnterTimestamp]}" =~ $print_re ]] || fail 'ActiveEnterTimestamp invalido'
[[ "${values[ExecMainStartTimestamp]}" =~ $print_re ]] || fail 'ExecMainStartTimestamp invalido'
[[ "${values[NRestarts]}" =~ ^[0-9]+$ ]] || fail 'NRestarts no es un entero no negativo'

if ! last_update=$(TZ=America/Lima "$DATE" '+%Y-%m-%d %H:%M:%S'); then
    fail 'no se pudo obtener la hora local'
fi
date_re='^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$'
[[ "$last_update" =~ $date_re ]] || fail 'hora local invalida'
last_update+=" -05"

printf -v content 'active_state=%s\nsub_state=%s\nactive_enter_timestamp=%s\nexec_main_start_timestamp=%s\nn_restarts=%s\nlast_update=%s\n' \
    "${values[ActiveState]}" \
    "${values[SubState]}" \
    "${values[ActiveEnterTimestamp]}" \
    "${values[ExecMainStartTimestamp]}" \
    "${values[NRestarts]}" \
    "$last_update"

if ! tmp=$("$MKTEMP" -- "${STATUS_DIR}/.status.tmp.XXXXXXXX"); then
    fail 'no se pudo crear el temporal'
fi
case "$tmp" in
    "$STATUS_DIR"/.status.tmp.*) ;;
    *) fail 'ruta temporal inesperada' ;;
esac

if ! printf '%s' "$content" > "$tmp"; then
    fail 'no se pudo escribir el temporal'
fi
if ! "$CHMOD" 0640 -- "$tmp"; then
    fail 'no se pudieron establecer los permisos del temporal'
fi
if ! owner_group=$("$STAT" -c '%U:%G' -- "$tmp"); then
    fail 'no se pudo verificar el propietario del temporal'
fi
[[ "$owner_group" == 'traccar-panel:www-data' ]] || fail 'propietario o grupo del temporal inesperado'

if ! "$MV" -fT -- "$tmp" "$STATUS_FILE"; then
    fail 'no se pudo publicar el estado atomicamente'
fi
tmp=''
