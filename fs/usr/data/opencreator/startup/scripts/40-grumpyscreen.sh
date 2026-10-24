#!/bin/sh
GRUMPY=/usr/data/grumpyscreen/grumpyscreen
[ -x "$GRUMPY" ] || exit 0

TOUCH=$(awk '
    /^N: Name=/ { name = tolower($0) }
    /^H: Handlers=/ && name ~ /goodix|touch/ {
        for (i = 2; i <= NF; i++)
            if ($i ~ /^event[0-9]+$/) { print "/dev/input/" $i; exit }
    }' /proc/bus/input/devices 2>/dev/null)
export LVGL_EVDEV_DEV=${TOUCH:-/dev/input/event2}

MACHINE=$(sed -n 's/^[[:space:]]*MACHINE=\([A-Za-z0-9]*\).*/\1/p' \
    /usr/prog/app_startup.sh /usr/prog/PROGRAM/runFirmwareExe.sh 2>/dev/null | head -n 1)
if [ "$MACHINE" = AD5X ]; then
    # pellcorp's default rotation (3) is for the K1; the AD5X is upright at 0
    export DISPLAY_ROTATE=0
    # the AD5X always has the IFS: MMU panel on unless another backend was chosen
    CFG=/usr/data/grumpyscreen/grumpyscreen.cfg
    [ -f "$CFG" ] && grep -q '^backend: none' "$CFG" &&
        sed -i '/^\[mmu\]/,/^\[/ s/^backend: none/backend: afc/' "$CFG"
fi

while true; do
    "$GRUMPY" >> /tmp/grumpyscreen.log 2>&1
    sleep 3
done
