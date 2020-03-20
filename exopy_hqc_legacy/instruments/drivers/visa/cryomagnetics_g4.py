# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright 2015-2018 by ExopyHqcLegacy Authors, see AUTHORS for more details.
#
# Distributed under the terms of the BSD license.
#
# The full license is in the file LICENCE, distributed with this software.
# -----------------------------------------------------------------------------
"""Driver for the Cryomagnetic superconducting magnet power supply 4G.
It is very close to the CS4 one but for a few bugs in the software:
- even though units is set to T, the fields are returned in kG
- some instructions need a semicolon at their end to be taken into account
(namely ULIM and RATE)
Also the fast sweep rate is stored in range 5 whereas it is stored in range
3 for the CS4.

"""
from ..driver_tools import (secure_communication,
                            instrument_property)
from .cryomagnetics_cs4 import CS4


class C4G(CS4):
    """Driver for the superconducting magnet power supply Cryomagnetics CG4.

    """

    @instrument_property
    @secure_communication()
    def target_field(self):
        """Field that the source will try to reach, in T.

        Iout is given in kG no matter the settings.

        """
        return float(self.ask('ULIM?;').strip('kG')) / 10

    @target_field.setter
    @secure_communication()
    def target_field(self, target):
        # convert target field from T to kG
        self.write('ULIM {};'.format(target * 10))

    @secure_communication()
    def read_output_field(self):
        """Read the current value of the output field.

        """
        return float(self.ask('IOUT?').strip('kG')) / 10

    @secure_communication()
    def read_persistent_field(self):
        """Read the current value of the persistent field.

        """
        return float(self.ask('IMAG?').strip('kG')) / 10

    @instrument_property
    @secure_communication()
    def field_sweep_rate(self):
        """Rate at which to ramp the field (T/min).

        """
        # converted from A/s to T/min
        rate = float(self.ask('RATE? 0'))
        return rate * (60 * self.field_current_ratio)

    @field_sweep_rate.setter
    @secure_communication()
    def field_sweep_rate(self, rate):
        # converted from T/min to A/s
        rate /= 60 * self.field_current_ratio
        self.write('RATE 0 {};'.format(rate))

    @instrument_property
    @secure_communication()
    def fast_sweep_rate(self):
        """Rate at which to ramp the field when the switch heater is off
        (T/min).

        """
        rate = float(self.ask('RATE? 5'))
        return rate * (60 * self.field_current_ratio)

    @fast_sweep_rate.setter
    @secure_communication()
    def fast_sweep_rate(self, rate):
        rate /= 60 * self.field_current_ratio
        self.write('RATE 5 {};'.format(rate))