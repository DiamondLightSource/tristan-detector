import logging
from enum import Enum


class ModeType(Enum):
    """Enumeration of operational modes"""

    time_energy = 0
    time_only = 1
    count = 2


class ProfileType(Enum):
    """Enumeration of operational modes"""

    standard = 0
    fast = 1
    energy = 2
    user = 3
    current = 4


class TriggerInType(Enum):
    """Enumeration of trigger in types"""

    internal = 0
    external_re = 1
    external_fe = 2
    external_lvds_re = 3
    external_lvds_fe = 4


class TriggerTimestampType(Enum):
    """Enumeration of trigger out types"""

    none = 0
    re = 1
    fe = 2
    both = 3


class TriggerInTerminationType(Enum):
    """Enumeration of trigger out types"""

    term_50ohm = 0
    hi_z = 1


class TriggerOutTerminationType(Enum):
    """Enumeration of trigger out types"""

    term_50ohm = 0
    lo_z = 1


class TriggerClockSourceType(Enum):
    """Enumeration of trigger out types"""

    internal = 0
    external = 1


class TriggerTZeroType(Enum):
    """Enumeration of trigger out types"""

    internal = 0
    external = 1
    off = 2


class TriggerOutType(Enum):
    """Enumeration of trigger out types"""

    follow_shutter = 0
    follow_shutter_read = 1
    one_per_acq_burst = 2
    busy = 3
    counter_select = 4
    tzero = 5
    sync = 6
    lvds = 7
    ttl = 8


class ParameterType(Enum):
    """Enumeration of all available types"""

    UNKNOWN = 0
    DICT = 1
    LIST = 2
    INT = 3
    DOUBLE = 4
    STRING = 5
    ENUM = 6


class Parameter:
    def __init__(
        self,
        name,
        data_type=ParameterType.UNKNOWN,
        value=None,
        callback=None,
        every_time=False,
    ):
        self._name = name
        self._datatype = data_type
        self._value = value
        self._callback = callback
        self._every_time = every_time

    @property
    def value(self):
        return self.get()["value"]

    def get(self):
        # Create the dictionary of information
        return_value = {"value": self._value, "type": self._datatype.value}
        logging.debug("Parameter return_value: %s", return_value)
        return return_value

    def set_value(self, value, callback=True):
        changed = False
        if self._value != value:
            self._value = value
            changed = True
        if self._callback is not None:
            if callback:
                if self._every_time:
                    self._callback(self._name, self._value)
                elif changed:
                    self._callback(self._name, self._value)


class EnumParameter(Parameter):
    def __init__(
        self, name, value=None, allowed_values=None, callback=None, every_time=False
    ):
        super().__init__(
            name,
            data_type=ParameterType.ENUM,
            value=value,
            callback=callback,
            every_time=every_time,
        )
        self._allowed_values = allowed_values

    def get(self):
        # Create the dictionary of information
        return_value = super().get()
        if self._allowed_values is not None:
            return_value["allowed_values"] = self._allowed_values
        return return_value

    def set_value(self, value, callback=True):
        logging.debug("enum set_value called with: %s", value)
        # Call super set with the name of the enum type
        if isinstance(value, EnumParameter):
            logging.debug("value considered an enum")
            super().set_value(value.name, callback)
        else:
            logging.debug("value is a string")
            super().set_value(value, callback)

    @property
    def index(self):
        return self.get()["allowed_values"].index(self.value)


class IntegerParameter(Parameter):
    def __init__(self, name, value=None, limits=None, callback=None, every_time=False):
        super().__init__(
            name,
            data_type=ParameterType.INT,
            value=value,
            callback=callback,
            every_time=every_time,
        )
        self._limits = limits

    def get(self):
        # Create the dictionary of information
        return_value = super().get()
        if self._limits is not None:
            return_value["limits"] = self._limits
        return return_value


class DoubleParameter(Parameter):
    def __init__(self, name, value=None, limits=None, callback=None, every_time=False):
        super().__init__(
            name,
            data_type=ParameterType.DOUBLE,
            value=value,
            callback=callback,
            every_time=every_time,
        )
        self._limits = limits

    def get(self):
        # Create the dictionary of information
        return_value = super().get()
        if self._limits is not None:
            return_value["limits"] = self._limits
        return return_value


class StringParameter(Parameter):
    def __init__(self, name, value=None, callback=None, every_time=False):
        super().__init__(
            name,
            data_type=ParameterType.STRING,
            value=value,
            callback=callback,
            every_time=every_time,
        )
