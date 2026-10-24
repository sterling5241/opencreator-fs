#!/bin/sh
# Releases MCU boards from their boot stage whenever Klipper can't reach one
# (power-on, FIRMWARE_RESTART). Port of c5_bridge.py's wake from
# opencreator-tunnel; see config-docs/CREATOR5_MCU_WAKE.md.

LOG=/usr/data/logs/c5-mcu-wake.log
PRINTER_LOG=/usr/data/opencreator/klipper/logs/printer.log
LOCK=/tmp/c5-mcu-wake.lock
RETRY_MIN=7

exec 9>"$LOCK"
flock -n 9 || exit 0

ACK=$(printf '\006')
IDENTIFY='\176\010\020\001\000\050\136\237\176'
STOPPED=

log() {
    echo "$(date '+%F %T') $*" >> "$LOG"
}

# mcu name -> tty, Klipper baud, wake parity order
MACHINE=$(sed -n 's/^[[:space:]]*MACHINE=\([A-Za-z0-9]*\).*/\1/p' \
    /usr/prog/app_startup.sh /usr/prog/PROGRAM/runFirmwareExe.sh 2>/dev/null | head -n 1)
board() {
    if [ "$MACHINE" = AD5X ]; then
        # only the eboard has the Ready/A boot stage; ttyS2 is the mainboard
        # (boots straight into the app) and ttyS4 the IFS (RS485, its
        # bootloader speaks XMODEM, not Ready/A)
        case "$1" in
            eboard) echo "/dev/ttyS5 230400 N E" ;;
            *) return 1 ;;
        esac
        return 0
    fi
    case "$1" in
        eheaterboard|heaterboard) echo "/dev/ttyS4 230400 N E" ;;
        eboard) echo "/dev/ttyS5 460800 E N" ;;
        levelboard) echo "/dev/ttyS7 230400 N E" ;;
        *) return 1 ;;
    esac
}

klippy_pids() {
    for d in /proc/[0-9]*; do
        tr '\0' ' ' < "$d/cmdline" 2>/dev/null | grep -q 'klippy/klippy\.py' &&
            echo "${d#/proc/}"
    done
}

resume_klippy() {
    [ -n "$STOPPED" ] && kill -CONT $STOPPED 2>/dev/null
    STOPPED=
}

set_line() {
    if [ "$3" = E ]; then par="parenb -parodd"; else par="-parenb"; fi
    stty -F "$1" "$2" raw -echo cs8 -cstopb -crtscts clocal cread -inpck $par
}

# Sets GOT=1 if anything arrived; succeeds once "Ready" is seen.
wait_banner() {
    GOT=0
    tail=
    end=$(($(date +%s) + 4))
    while [ "$(date +%s)" -lt "$end" ]; do
        c=
        IFS= read -r -n 1 -t 0.2 c <&3 || [ -n "$c" ] || continue
        GOT=1
        tail="$tail$c"
        case "$tail" in *Ready*) return 0 ;; esac
        [ ${#tail} -gt 16 ] && tail=${tail#????????}
    done
    return 1
}

# Succeeds once byte $1 arrives; gives up after ~0.3 s of silence.
read_until() {
    idle=0 bytes=0
    while [ $idle -lt 6 ] && [ $bytes -lt 256 ]; do
        c=
        if IFS= read -r -n 1 -t 0.05 c <&3 || [ -n "$c" ]; then
            bytes=$((bytes + 1))
            [ "$c" = "$1" ] && return 0
        else
            idle=$((idle + 1))
        fi
    done
    return 1
}

send_ack() {
    for try in 1 2 3; do
        printf A >&3
        read_until "$ACK" && return 0
    done
    return 1
}

# Klipper answers an identify with a frame ending in 0x7e ("~").
probe() {
    n=0
    while [ $n -lt 256 ] && IFS= read -r -n 1 -t 0.05 c <&3; do
        n=$((n + 1))
    done
    printf "$IDENTIFY" >&3
    read_until "~"
}

wake() {
    name=$1 tty=$2 baud=$3
    shift 3
    STOPPED=$(klippy_pids)
    [ -n "$STOPPED" ] && kill -STOP $STOPPED
    saved=$(stty -g -F "$tty") || { resume_klippy; return; }
    exec 3<>"$tty"
    result="failed: no banner"
    for parity in "$@"; do
        set_line "$tty" 115200 "$parity"
        if wait_banner; then
            if send_ack; then
                result="ok (parity $parity)"
                break
            fi
            set_line "$tty" "$baud" N
            if probe; then
                result="ok (parity $parity, ack lost)"
                break
            fi
            result="failed: no ack"
        fi
        [ "$GOT" = 1 ] || break
    done
    exec 3<&-
    stty -F "$tty" "$saved"
    resume_klippy
    log "$name: wake $result"
}

log "started"
tail -n 0 -F "$PRINTER_LOG" 2>/dev/null | {
    trap 'resume_klippy; exit' INT TERM HUP
    while IFS= read -r line; do
        case "$line" in
            *"mcu '"*"': Timeout on connect"*) ;;
            *) continue ;;
        esac
        name=${line#*mcu \'}
        name=${name%%\'*}
        b=$(board "$name") || continue
        eval "last=\${last_$name:-0}"
        [ $(($(date +%s) - last)) -lt $RETRY_MIN ] && continue
        log "$name: identify unanswered"
        wake "$name" $b
        eval "last_$name=$(date +%s)"
    done
}
