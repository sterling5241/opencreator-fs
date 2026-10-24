#!/bin/sh
LAUNCHER_LOG="/tmp/opencreator.log"
OC=/usr/data/opencreator/klipper
KPY=$OC/klippy-env/bin/python
# python-hf/cc/bin/gcc rebuilds c_helper.so (hard-float) after Kalico updates.
export PATH=/usr/data/python-hf/cc/bin:$PATH:/opt/bin

log_launcher() {
    echo "$1" >> "$LAUNCHER_LOG"
}

# AFC stops with an error while its variables file is missing or empty; it
# fills the file in itself once it has state to save.
for AFC_VARS in "$OC/config/AFC/AFC.var.unit" "$OC/config/AFC/AFC.var"; do
    if [ ! -s "$AFC_VARS" ]; then
        mkdir -p "$OC/config/AFC"
        echo '{}' > "$AFC_VARS"
    fi
done

# printer.base.cfg gets the Pro-only hardware (chamber heater, chamber and aux
# fans: printer.pro.cfg) through printer.model.cfg. The model is read from the
# stock boot script, as the installer does.
MODEL_CFG=$OC/config/printer.model.cfg
MACHINE=$(sed -n 's/^[[:space:]]*MACHINE=\([A-Za-z0-9]*\).*/\1/p' \
    /usr/prog/app_startup.sh /usr/prog/PROGRAM/runFirmwareExe.sh 2>/dev/null | head -n 1)
case $MACHINE in
    Creator5Pro) MODEL_TEXT='# Written at boot: Creator 5 Pro
[include printer.pro.cfg]' ;;
    Creator5) MODEL_TEXT='# Written at boot: Creator 5 (no chamber heater, chamber fans or aux fan)' ;;
    AD5X) MODEL_TEXT='# Written at boot: AD5X' ;;
    *) MODEL_TEXT= ;;
esac
if [ -n "$MODEL_TEXT" ]; then
    [ "$(cat "$MODEL_CFG" 2>/dev/null)" = "$MODEL_TEXT" ] || printf '%s\n' "$MODEL_TEXT" > "$MODEL_CFG"
elif [ ! -f "$MODEL_CFG" ]; then
    log_launcher "Printer model unknown; keeping the Creator 5 Pro hardware in the config"
    printf '# Written at boot: model unknown, assumed Creator 5 Pro\n[include printer.pro.cfg]\n' > "$MODEL_CFG"
fi

PLUGINS=/usr/data/opencreator/plugin-manager/oc-plugin
[ -d /opt/bin ] && [ -f "$PLUGINS" ] && ln -sf "$PLUGINS" /opt/bin/oc-plugin

while true; do
    if [ -x "$KPY" ]; then
        # Plugin modules and configs, redone before every start (Fluidd updates plugins with git pull)
        [ -f "$PLUGINS" ] && sh "$PLUGINS" sync --only klipper >> "$LAUNCHER_LOG" 2>&1
        log_launcher "Klippy is starting..."

        "$KPY" "$OC/klipper/klippy/klippy.py" "$OC/config/printer.cfg" -l "$OC/logs/printer.log" -a /tmp/uds

        log_launcher "Klippy exited; see $OC/logs/printer.log. Restarting in 3 s."
        log_launcher "ERR CODE 0 - Klippy"
    fi
    sleep 3
done
