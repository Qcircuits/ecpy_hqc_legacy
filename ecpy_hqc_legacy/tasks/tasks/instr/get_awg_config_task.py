# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright 2015-2016 by EcpyHqcLegacy Authors, see AUTHORS for more details.
#
# Distributed under the terms of the BSD license.
#
# The full license is in the file LICENCE, distributed with this software.
# -----------------------------------------------------------------------------
"""Tasks to set the parameters of arbitrary waveform generators.

"""
from __future__ import (division, unicode_literals, print_function,
                        absolute_import)

from atom.api import set_default

from ecpy.tasks.api import (InstrumentTask)


class GetAWGConfigTask(InstrumentTask):
    """ Task to get the AWG channel configurations as a database entry

    """

    database_entries = set_default({'awg_chan_config': {}})


    def perform(self):
        """Default interface behavior.

        """
        config ={}
        for ch_id in self.driver.defined_channels:
            ch = self.driver.get_channel(ch_id)
            config['ANALOG_AMPLITUDE_' + str(ch_id)] = ch.vpp
            config['ANALOG_OFFSET_' + str(ch_id)] = ch.offset
            config['MARKER1_LOW_' + str(ch_id)] = ch.marker1_low_voltage 
            config['MARKER1_HIGH_' + str(ch_id)] = ch.marker1_high_voltage
            config['MARKER1_SKEW_' + str(ch_id)] = ch.marker1_delay
            config['MARKER2_LOW_' + str(ch_id)] = ch.marker2_low_voltage 
            config['MARKER2_HIGH_' + str(ch_id)] = ch.marker2_high_voltage
            config['MARKER2_SKEW_' + str(ch_id)] = ch.marker2_delay

        self.write_in_database('awg_chan_config', config)                