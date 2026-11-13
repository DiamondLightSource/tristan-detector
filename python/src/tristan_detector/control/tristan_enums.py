"""Enumerations of the Tristan detector's enumerated config values

These are the single source of truth for the allowed values of the detector's enum
config parameters, used by TristanDetector for parameter metadata and by the control
simulator for its default config.
"""

from enum import Enum


class ModeType(Enum):
    """Operational modes (config/mode)"""

    time_energy = 0
    time_only = 1
    count = 2


class ProfileType(Enum):
    """Operational profiles (config/profile)"""

    standard = 0
    fast = 1
    energy = 2
    user = 3
    current = 4


class TriggerInType(Enum):
    """Trigger input sources (config/trigger/start, config/trigger/stop)"""

    internal = 0
    external_re = 1
    external_fe = 2
    external_lvds_re = 3
    external_lvds_fe = 4


class TriggerTimestampType(Enum):
    """Trigger edges to timestamp (config/trigger/timestamp/*)"""

    none = 0
    re = 1
    fe = 2
    both = 3


class TriggerInTerminationType(Enum):
    """TTL trigger input termination (config/trigger/ttl_in_term)"""

    term_50ohm = 0
    hi_z = 1


class TriggerOutTerminationType(Enum):
    """TTL trigger output termination (config/trigger/ttl_out_term)"""

    term_50ohm = 0
    lo_z = 1


class TriggerClockSourceType(Enum):
    """Primary clock source (config/trigger/primary_clock_source)"""

    internal = 0
    external = 1


class TriggerTZeroType(Enum):
    """T-zero source (config/trigger/tzero)"""

    internal = 0
    external = 1
    off = 2


class TriggerOutType(Enum):
    """Trigger output signals (config/trigger/ttl_out, config/trigger/lvds_out)"""

    follow_shutter = 0
    follow_shutter_read = 1
    one_per_acq_burst = 2
    busy = 3
    counter_select = 4
    tzero = 5
    sync = 6
    lvds = 7
    ttl = 8
