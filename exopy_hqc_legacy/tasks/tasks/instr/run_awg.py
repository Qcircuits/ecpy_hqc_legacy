# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright 2015-2018 by ExopyHqcLegacy Authors, see AUTHORS for more details.
#
# Distributed under the terms of the BSD license.
#
# The full license is in the file LICENCE, distributed with this software.
# -----------------------------------------------------------------------------
"""Tasks to set the parameters of arbitrary waveform generators.

"""
import logging
import time
import numbers

from atom.api import (Float, Unicode, set_default)

from exopy.tasks.api import (InstrumentTask, validators)


class RunAWGTask(InstrumentTask):
    """ Task to set AWG run mode

    """
    #: Switch to choose the AWG run mode: on or off
    switch = Unicode('Off').tag(pref=True, feval=validators.SkipLoop())
    delay = Unicode('0').tag(pref=True,
                                 feval=validators.SkipLoop(types=numbers.Real))

    database_entries = set_default({'output': 0})

    def perform(self, switch=None):
        """Default interface behavior.

        """
        delay = self.format_and_eval_string(self.delay)
        if switch is None:
            switch = self.format_and_eval_string(self.switch)

        if switch == 'On' or switch == 1:
            print('On')
            self.driver.send_event() #goes with a 'Event jump to' 1
#            print(delay)
            self.driver.run_awg(1, delay=delay) #delay needed when loading
                                                     #large nb of sequences
            self.write_in_database('output', 1)
        elif switch == 'Event':
            print('Event')
            time.sleep(delay)
            self.driver.send_event()
        elif switch == 'Rearm':
            print('Rearm')
            time.sleep(delay)
            success=False
            while not success:
                self.driver.send_event()
                pos = int(self.driver.ask_sequencer_pos())
                print(pos)
                if pos==1:
                    success=True
                print(success)
            time.sleep(delay)
        else:
            print('Off')
            time.sleep(delay)
            self.driver.run_awg(0)
            self.write_in_database('output', 0)
        log = logging.getLogger(__name__)
        msg = 'AWG running state OK'
        log.debug(msg)
