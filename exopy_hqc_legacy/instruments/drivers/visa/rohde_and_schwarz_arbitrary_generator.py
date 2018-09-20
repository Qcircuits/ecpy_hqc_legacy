# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright 2015-2017 by ExopyHqcLegacy Authors, see AUTHORS for more details.
#
# Distributed under the terms of the BSD license.
#
# The full license is in the file LICENCE, distributed with this software.
# -----------------------------------------------------------------------------
"""Drivers for Rohde and Schwarz ArbitraryGenerator using VISA library.

"""
import re
from textwrap import fill
from inspect import cleandoc

from visa import VisaTypeError

from ..driver_tools import (InstrIOError, instrument_property,
                            secure_communication)
from ..visa_tools import VisaInstrument


class RohdeSchwarzHMF2550(VisaInstrument):
    """
    Generic driver for Rohde and Schwarz HMF2550 ArbitraryGenerator,
    using the VISA library.

    This driver does not give access to all the functionnality of the
    instrument but you can extend it if needed. See the documentation of
    the driver_tools module for more details about writing instruments
    drivers.

    Parameters
    ----------
    see the `VisaInstrument` parameters

    Attributes
    ----------
    frequency_unit : str
        Frequency unit used by the driver. The default unit is 'GHz'. Other
        valid units are : 'MHz', 'KHz', 'Hz'
    frequency : float, instrument_property
        Fixed frequency of the output signal.
    power : float, instrument_property
        Fixed power of the output signal.
    output : bool, instrument_property
        State of the output 'ON'(True)/'OFF'(False).

    Notes
    -----
    This driver has been written for the  but might work for other
    models using the same SCPI commands.

    """
    def __init__(self, connection_info, caching_allowed=True,
                 caching_permissions={}, auto_open=True):

        super(RohdeSchwarzHMF2550, self).__init__(connection_info,
                                                  caching_allowed,
                                                  caching_permissions,
                                                  auto_open)
        self.frequency_unit = 'Hz'
        self.period_unit = 's'
        self.write_termination = '\n'
        self.read_termination = '\n'

    @instrument_property
    @secure_communication()
    def frequency(self):
        """Frequency of the output signal.

        """
        freq = self.ask_for_values('FREQ?')
        if freq:
            return freq[0]
        else:
            raise InstrIOError

    @frequency.setter
    @secure_communication()
    def frequency(self, value):
        """Frequency setter method.

        """
        unit = self.frequency_unit
        self.write('FREQ {}{}'.format(value, unit))
        result = self.ask_for_values('FREQ?')
        if result:
            if unit == 'GHz':
                result[0] /= 1e9
            elif unit == 'MHz':
                result[0] /= 1e6
            elif unit == 'KHz':
                result[0] /= 1e3
            if abs(result[0] - value) > 1e-12:
                mes = 'Instrument did not set correctly the frequency.'
                raise InstrIOError(mes)            

    @instrument_property
    @secure_communication()
    def period(self):
        """Period of the output signal.

        """
        period = self.ask_for_values('PER?')
        if period:
            return period[0]
        else:
            raise InstrIOError

    @period.setter
    @secure_communication()
    def period(self, value):
        """Period setter method.

        """
        unit = self.period_unit
        self.write('PER {}{}'.format(value, unit))
        result = self.ask_for_values('PER?')
        print(result[0])
        print(value)
        if result:
            if unit == 'ns':
                result[0] /= 1e-9
            elif unit == 'us':
                result[0] /= 1e-6
            elif unit == 'ms':
                result[0] /= 1e-3
            if abs(result[0] - value) > 1e-12:
                mes = 'Instrument did not set correctly the period.'
                raise InstrIOError(mes)    

    @instrument_property
    @secure_communication()
    def output(self):
        """Output state of the source.

        """
        output = self.ask(':OUTP?')
        if output is not None:
            if output == 'OFF':
                return False
            elif output == 'ON':
                return True
            else:
                mes = 'output is not standard, received %s ' % output
                raise InstrIOError(mes)
        else:
            mes = 'HMF arbitrary generator did not return its output'
            raise InstrIOError(mes)

    @output.setter
    @secure_communication()
    def output(self, value):
        """Output setter method.

        """
        on = re.compile('on', re.IGNORECASE)
        off = re.compile('off', re.IGNORECASE)
        if on.match(value) or value == 1:
            self.write(':OUTPUT ON')
            if not self.output:
                raise InstrIOError(cleandoc('''Instrument did not set correctly
                                        the output'''))
        elif off.match(value) or value == 0:
            self.write(':OUTPUT OFF')
            if self.output:
                raise InstrIOError(cleandoc('''Instrument did not set correctly
                                        the output'''))
        else:
            mess = fill(cleandoc('''The invalid value {} was sent to
                        switch_on_off method''').format(value), 80)
            raise VisaTypeError(mess)
