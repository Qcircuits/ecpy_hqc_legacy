# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright 2015-2016 by EcpyHqcLegacy Authors, see AUTHORS for more details.
#
# Distributed under the terms of the BSD license.
#
# The full license is in the file LICENCE, distributed with this software.
# -----------------------------------------------------------------------------
"""Task to apply a magnetic field.

"""
from __future__ import (division, unicode_literals, print_function,
                        absolute_import)

from atom.api import (Unicode, Float, Bool, set_default)

from epy.tasks.api import InstrumentTask


class ApplyMagFieldTask(InstrumentTask):
    """Use a supraconducting magnet to apply a magnetic field. Parallel task.

    """
    # Target magnetic field (dynamically evaluated)
    target_field = Unicode().tag(pref=True, feval='Skip_empty')

    # Rate at which to sweep the field.
    rate = Float(0.01).tag(pref=True)

    # Whether to stop the switch heater after setting the field.
    auto_stop_heater = Bool(True).tag(pref=True)

    # Time to wait before bringing the field to zero after closing the switch
    # heater.
    post_switch_wait = Float(30.0).tag(pref=True)

    parallel = set_default({'activated': True, 'pool': 'instr'})
    database_entries = set_default({'Bfield': 0.01})

    def perform(self, target_value=None):
        """Apply the specified magnetic field.

        """
        if (self.driver.owner != self.name or
                not self.driver.check_connection()):
            self.driver.owner = self.task_name
            self.driver.make_ready()

        if target_value is None:
            target_value = self.format_and_eval_string(self.target_field)
        self.driver.go_to_field(target_value, self.rate, self.auto_stop_heater,
                                self.post_switch_wait)
        self.write_in_database('Bfield', target_value)