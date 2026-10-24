#!/bin/sh
MACHINE=$(sed -n 's/^[[:space:]]*MACHINE=\([A-Za-z0-9]*\).*/\1/p' \
    /usr/prog/app_startup.sh /usr/prog/PROGRAM/runFirmwareExe.sh 2>/dev/null | head -n 1)
# the AD5X's X2600 kernel and userland are NaN2008; no legacy-NaN switch
[ "$MACHINE" = AD5X ] && exit 0
case "$(ls /usr/prog/PROGRAM/kernel/ 2>/dev/null | head -n 1)" in
    2.0.1|2.0.2|2.0.3|2.0.4|2.0.5|2.0.6)
        busybox devmem 0x00a130d1 8 1
        ;;
    2.0.7)
        busybox devmem 0x00B330D1 8 1
        ;;
    2.0.8)
        busybox devmem 0x00B030D1 8 1
        ;;
    *)
        echo "Unknown kernel package; legacy NaN not enabled" >&2
        exit 1
        ;;
esac
