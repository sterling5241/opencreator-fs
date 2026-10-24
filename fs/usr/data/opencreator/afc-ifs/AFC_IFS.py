# FlashForge AD5X IFS unit for Armored Turtle AFC
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from __future__ import annotations

import traceback

from configparser import Error as config_error

try: from extras.AFC_utils import ERROR_STR
except:
    trace=traceback.format_exc()
    err_str = f"Error when trying to import AFC_utils.ERROR_STR\n{trace}"
    raise config_error(err_str)

try: from extras.AFC_lane import MoveDirection
except: raise config_error(ERROR_STR.format(import_lib="AFC_lane", trace=traceback.format_exc()))

try: from extras.AFC_HTLF import AFC_HTLF
except: raise config_error(ERROR_STR.format(import_lib="AFC_HTLF", trace=traceback.format_exc()))

SILK_SAMPLE_TIME  = 0.001
SILK_SAMPLE_COUNT = 20
SILK_REPORT_TIME  = 0.100

class AFC_IFS(AFC_HTLF):
    def __init__(self, config):
        super().__init__(config)
        self.slot_angle         = config.getfloat("slot_angle", 90.)
        self.home_backoff       = config.getfloat("home_backoff", 90.)
        self.home_search        = config.getfloat("home_search", 360.)
        self.neutral_angle      = config.getfloat("neutral_angle", 45.)
        self.silk_present_low   = config.getfloat("silk_present_low", 900. / 4095.)
        self.silk_present_high  = config.getfloat("silk_present_high", 3100. / 4095.)
        self.silk_empty_low     = config.getfloat("silk_empty_low", 1001. / 4095.)
        self.silk_empty_high    = config.getfloat("silk_empty_high", 2999. / 4095.)
        self.silk_pins          = [p.strip() for p in config.get("silk_pins").split(",")]
        self.silk_state         = [None] * len(self.silk_pins)
        self.auto_load          = config.getboolean("auto_load", True)
        self.auto_load_max      = config.getfloat("auto_load_max", 650.)
        self.auto_load_step     = config.getfloat("auto_load_step", 10.)
        self.park_dist          = config.getfloat("park_dist", 70.)
        self.auto_load_busy     = False
        self.selector_pos       = None
        # purge chute, stock firmwareExe printClearGoPos / clear_brush positions
        self.chute_x            = config.getfloat("chute_x", 52.5)
        self.chute_y            = config.getfloat("chute_y", 230.5)
        self.chute_y_out        = config.getfloat("chute_y_out", 220.)
        self.brush_x_min        = config.getfloat("brush_x_min", 65.)
        self.brush_x_max        = config.getfloat("brush_x_max", 73.)
        self.brush_x_out        = config.getfloat("brush_x_out", 78.)
        self.brush_count        = config.getint("brush_count", 2)
        self.ifs_gcode          = self.printer.lookup_object("gcode")
        self.ifs_gcode.register_command("AD5X_PARK", self.cmd_AD5X_PARK, desc="Move into the purge chute like stock")
        self.ifs_gcode.register_command("AD5X_POOP", self.cmd_AD5X_POOP, desc="Purge in the chute like stock")
        self.ifs_gcode.register_command("AD5X_BRUSH", self.cmd_AD5X_BRUSH, desc="Stock brush wipe, ends out of the chute")
        self.cut_approach_y     = config.getfloat("cut_approach_y", 10.)
        self.ifs_gcode.register_command("AD5X_CUT", self.cmd_AD5X_CUT, desc="Stock approach to the cutter, then AFC_CUT")

        ppins = self.printer.lookup_object("pins")
        for idx, pin in enumerate(self.silk_pins):
            mcu_adc = ppins.setup_pin("adc", pin)
            mcu_adc.setup_adc_sample(SILK_SAMPLE_TIME, SILK_SAMPLE_COUNT)
            mcu_adc.setup_adc_callback(SILK_REPORT_TIME,
                                       lambda t, v, i=idx: self._silk_callback(i, t, v))

    def handle_connect(self):
        super().handle_connect()
        self.logo = '<span class=success--text>IFS Ready\n</span>'
        self.logo_error = '<span class=error--text>IFS Not Ready</span>\n'
        if self.afc.park_cmd == "AFC_PARK":
            self.afc.park_cmd = "AD5X_PARK"
        if self.afc.poop_cmd == "AFC_POOP":
            self.afc.poop_cmd = "AD5X_POOP"
        if self.afc.wipe_cmd == "AFC_BRUSH":
            self.afc.wipe_cmd = "AD5X_BRUSH"
        if self.afc.tool_cut_cmd == "AFC_CUT":
            self.afc.tool_cut_cmd = "AD5X_CUT"
        # stock: feed motor off while printing, the extruder pulls the lane through
        drive = self.drive_stepper_obj
        drive.sync_to_extruder = lambda *args, **kwargs: drive.do_enable(False)

    # stock fourInOneCut: front strip first, then along X to the cutter start
    def cmd_AD5X_CUT(self, gcmd):
        cut_vars = self.printer.lookup_object("gcode_macro _AFC_CUT_TIP_VARS").variables
        pin_x, pin_y = [float(v) for v in cut_vars["pin_loc_xy"]]
        park_x = pin_x + float(cut_vars["pin_park_dist"])
        self.ifs_gcode.run_script_from_command("\n".join([
            "SAVE_GCODE_STATE NAME=_ad5x_cut", "G90",
            "G1 Y%.3f F18000" % self.cut_approach_y,
            "G1 Y%.3f" % pin_y,
            "G1 X%.3f F12000" % park_x,
            "M400", "RESTORE_GCODE_STATE NAME=_ad5x_cut"]))
        params = " ".join("%s=%s" % (k, v) for k, v in gcmd.get_command_parameters().items())
        self.ifs_gcode.run_script_from_command("AFC_CUT " + params)

    # prep: stock homes once at power-on and otherwise trusts the silk sensors,
    # so skip AFC_HTLF's re-home per lane and never move lanes during prep
    def system_Test(self, cur_lane, delay, assignTcmd, enable_movement):
        cur_lane.prep_state = cur_lane.load_state
        if not self.prep_homed:
            if not self.return_to_home():
                return False
        status = super(AFC_HTLF, self).system_Test(cur_lane, delay, assignTcmd, False)
        return self.prep_homed and status

    # stock enters and leaves the chute along Y only
    def _chute_park(self):
        pos = self.printer.lookup_object("toolhead").get_position()
        cmds = ["SAVE_GCODE_STATE NAME=_ifs_chute", "G90"]
        if pos[0] != self.chute_x or pos[1] != self.chute_y:
            if pos[1] > self.chute_y_out:
                cmds.append("G1 Y%.3f F3000" % self.chute_y_out)
            cmds += ["G1 X%.3f F12000" % self.chute_x,
                     "G1 Y%.3f F12000" % self.chute_y_out,
                     "G1 Y%.3f F3000" % self.chute_y]
        cmds += ["M400", "RESTORE_GCODE_STATE NAME=_ifs_chute"]
        self.ifs_gcode.run_script_from_command("\n".join(cmds))

    def cmd_AD5X_PARK(self, gcmd):
        self._chute_park()

    def cmd_AD5X_POOP(self, gcmd):
        self._chute_park()
        params = " ".join("%s=%s" % (k, v) for k, v in gcmd.get_command_parameters().items())
        self.ifs_gcode.run_script_from_command("AFC_POOP " + params)

    def cmd_AD5X_BRUSH(self, gcmd):
        cmds = ["SAVE_GCODE_STATE NAME=_ifs_brush", "G90",
                "G1 Y%.3f F3000" % self.chute_y_out,
                "G1 X%.3f F12000" % self.brush_x_out,
                "G1 Y%.3f" % self.chute_y]
        for i in range(self.brush_count):
            cmds += ["G1 X%.3f" % self.brush_x_min, "G1 X%.3f" % self.brush_x_max]
        cmds += ["G1 X%.3f" % self.brush_x_min,
                 "G1 X%.3f" % self.brush_x_out,
                 "G1 Y%.3f" % self.chute_y_out,
                 "M400", "RESTORE_GCODE_STATE NAME=_ifs_brush"]
        self.ifs_gcode.run_script_from_command("\n".join(cmds))

    def _silk_callback(self, idx, read_time, value):
        present = self.silk_state[idx]
        if value < self.silk_present_low or value > self.silk_present_high:
            present = True
        elif self.silk_empty_low <= value <= self.silk_empty_high:
            present = False
        if present is None or present == self.silk_state[idx]:
            return
        lane = self._lane_for_index(idx + 1)
        if lane is None:
            return
        self.silk_state[idx] = present
        eventtime = self.afc.reactor.monotonic()
        self.afc.reactor.register_callback(
            lambda e, l=lane, s=present: self._set_lane_load(l, e, s))

    def _set_lane_load(self, lane, eventtime, state):
        lane.load_callback(eventtime, state)
        lane.handle_load_runout(eventtime, state)

    def on_filament_insert(self, lane):
        super().on_filament_insert(lane)
        if self.auto_load:
            self.afc.reactor.register_callback(lambda e, l=lane: self._auto_load(l))

    # stock: feed a new spool until the toolhead sensor, then park it back
    def _auto_load(self, lane):
        if self.auto_load_busy or self.afc.function.is_printing():
            return
        if lane.get_toolhead_pre_sensor_state():
            self.logger.info("{}: toolhead sensor has filament, not auto loading".format(lane.name))
            return
        self.auto_load_busy = True
        try:
            fed = 0.
            while not lane.get_toolhead_pre_sensor_state() and fed < self.auto_load_max:
                lane.move(self.auto_load_step, lane.short_moves_speed, lane.short_moves_accel)
                fed += self.auto_load_step
                self.afc.reactor.pause(self.afc.reactor.monotonic() + 0.2)
            if lane.get_toolhead_pre_sensor_state():
                lane.move(-self.park_dist, lane.short_moves_speed, lane.short_moves_accel)
                self.logger.info("{}: auto loaded, toolhead sensor after {:.0f}mm, parked {:.0f}mm back".format(
                    lane.name, fed, self.park_dist))
            else:
                self.afc.error.AFC_error("{}: toolhead sensor not reached after {:.0f}mm".format(lane.name, fed), False)
        finally:
            self.return_to_home()
            self.auto_load_busy = False

    def _lane_for_index(self, index):
        for lane in self.lanes.values():
            if lane.index == index:
                return lane
        return None

    def _home(self):
        if self.home_state:
            self.selector_stepper_obj.move(self.home_backoff * MoveDirection.NEG,
                                           self.selector_movement_speed,
                                           self.selector_movement_accel,
                                           False)
            if self.home_state:
                self.failed_to_home = True
                self.afc.error.AFC_error("Failed to leave home sensor on {}".format(self.name), False)
                return False

        homed, self._homed_distance = self.selector_stepper_obj.do_homing_move(
            self.home_search * MoveDirection.POS,
            self.selector_movement_speed,
            self.selector_movement_accel,
            self.home_endstop_name,
            assist_active=False
        )
        if not homed:
            self.failed_to_home = True
            self.afc.error.AFC_error("Failed to home {}".format(self.name), False)
            return False

        self.failed_to_home = False
        self.prep_homed = True
        self.selector_pos = 0.
        return True

    # stock homes once and then moves by position; slot 1 is at the home sensor
    def _ensure_homed(self, prep=False):
        if prep or self.failed_to_home or self.selector_pos is None:
            return self._home()
        return True

    def _move_to(self, target):
        dist = target - self.selector_pos
        if abs(dist) > 0.001:
            self.selector_stepper_obj.move(dist,
                                           self.selector_movement_speed,
                                           self.selector_movement_accel,
                                           False)
        self.selector_pos = target

    def return_to_home(self, prep=False, disable_selector=True):
        if not self._ensure_homed(prep):
            return False
        if disable_selector:
            # park between slots so no lane is held
            self._move_to(self.neutral_angle)
            self.selector_stepper_obj.do_enable(False)
        else:
            self._move_to(0.)
        self.current_selected_lane = None
        return True

    def calculate_lobe_movement(self, lane_index:int):
        return (lane_index - 1) * self.slot_angle

    def select_lane(self, lane, disable_selector=False):
        if "stepper" in lane.fullname.lower():
            return False, 0.0
        try:
            if self.current_selected_lane != lane:
                if not self._ensure_homed():
                    self.logger.error("IFS: failed to home when selecting {}".format(lane.name))
                    return False, 0.0
                self._move_to(self.calculate_lobe_movement(lane.index))
                self.current_selected_lane = lane
                return True, self._homed_distance
        finally:
            if disable_selector:
                self.selector_stepper_obj.do_enable(False)
        return True, 0.0

def load_config_prefix(config):
    return AFC_IFS(config)
