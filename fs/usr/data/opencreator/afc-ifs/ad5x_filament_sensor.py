# FlashForge AD5X analog filament sensor (toolhead), for AFC u1_filament_sensor_name
#
# This file may be distributed under the terms of the GNU GPLv3 license.

SAMPLE_TIME  = 0.001
SAMPLE_COUNT = 8
REPORT_TIME  = 0.100

class RunoutHelper:
    def __init__(self, config):
        self.name = config.get_name().split()[-1]
        self.reactor = config.get_printer().get_reactor()
        self.event_delay = config.getfloat("event_delay", 3.0, minval=0.)
        self.min_event_systime = self.reactor.NEVER
        self.filament_present = False
        self.sensor_enabled = True
        self.runout_pause = False
        self.runout_gcode = None
        self._runout_event_handler = None

    def note_filament_present(self, state, force=False):
        self.filament_present = state

class AD5XFilamentSensor:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name().split()[-1]
        self.present_below = config.getfloat("present_below", 0.3)
        self.present_above = config.getfloat("present_above", 0.72)
        self.runout_helper = RunoutHelper(config)
        self.value = 0.
        self.state = None
        pin = config.get("sensor_pin")
        ppins = self.printer.lookup_object("pins")
        ppins.allow_multi_use_pin(pin)
        self.mcu_adc = ppins.setup_pin("adc", pin)
        self.mcu_adc.setup_adc_sample(SAMPLE_TIME, SAMPLE_COUNT)
        self.mcu_adc.setup_adc_callback(REPORT_TIME, self._adc_callback)
        self.printer.add_object("filament_motion_sensor %s" % (self.name,), self)

    def _adc_callback(self, read_time, value):
        self.value = value
        state = value <= self.present_below or value >= self.present_above
        if state == self.state:
            return
        self.state = state
        self.runout_helper.note_filament_present(state)

    def get_status(self, eventtime):
        return {"filament_detected": bool(self.runout_helper.filament_present),
                "enabled": bool(self.runout_helper.sensor_enabled),
                "value": self.value}

def load_config_prefix(config):
    return AD5XFilamentSensor(config)
