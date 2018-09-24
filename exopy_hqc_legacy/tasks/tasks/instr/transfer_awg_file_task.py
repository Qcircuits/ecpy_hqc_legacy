# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright 2015-2016 by EcpyHqcLegacy Authors, see AUTHORS for more details.
#
# Distributed under the terms of the BSD license.
#
# The full license is in the file LICENCE, distributed with this software.
# -----------------------------------------------------------------------------
"""Task to generate, transfer and load an .awg file on AWG

"""
import os
import struct
from io import BytesIO
from traceback import format_exc
import time
from collections import OrderedDict
import numpy as np
from atom.api import Value, Unicode, Float, Typed, Bool, set_default
from exopy.tasks.api import (InstrumentTask)
from exopy.utils.atom_util import ordered_dict_from_pref, ordered_dict_to_pref


class TransferAWGFileTask(InstrumentTask):
    """Build and transfer a pulse sequence to an instrument through generation
    of an .awg file

    """
    #: Sequence path for the case of sequence simply referenced.
    sequence_path = Unicode().tag(pref=True)

    #: Time stamp of the last modification of the sequence file.
    sequence_timestamp = Float().tag(pref=True)

    #: Sequence of pulse to compile and transfer to the instrument.
    sequence = Value()

    #: Global variable to use for the sequence.
    sequence_vars = Typed(OrderedDict, ()).tag(pref=(ordered_dict_to_pref,
                                                     ordered_dict_from_pref))

    #: Loop variables: channels on which the loop will be done, loop parameters
    #: names, start value, stop value and number of points per loop

    parameters = Typed(OrderedDict, ()).tag(pref=[ordered_dict_to_pref,
                                                   ordered_dict_from_pref])
    
    database_entries = set_default({'num_loop': 1})

    #: wait for trigger before playing each sequence
    wait_trigger = Bool(False).tag(pref=True)

    #: internal or external trigger
    internal_trigger = Bool(False).tag(pref=True)

    #: Internal trigger period in mus
    trigger_period = Unicode('20').tag(pref=True)

    #: Take an external event to enter/exit the loop
    start_with_event =  Bool(False).tag(pref=True)

    #: AWG Channel Config Dict
    awg_configuration = Unicode('').tag(pref=True)


    def check(self, *args, **kwargs):
        """Check that the sequence can be compiled.

        """
        test, traceback = super(TransferAWGFileTask,
                                self).check(*args, **kwargs)
        err_path = self.path + '/' + self.name + '-'

        msg = 'Failed to evaluate {} ({}): {}'
        seq = self.sequence
        for k, v in self.sequence_vars.items():
            try:
                seq.external_vars[k] = self.format_and_eval_string(v)
            except Exception:
                test = False
                traceback[err_path+k] = msg.format(k, v, format_exc())

        if not test:
            return test, traceback

        context = seq.context
        res, infos, errors = context.compile_and_transfer_sequence(seq)

        if not res:
            traceback[err_path+'compil'] = errors
            return False, traceback

        for k, v in infos.items():
            self.write_in_database(k, v)

        if self.sequence_path:
            if not (self.sequence_timestamp ==
                    os.path.getmtime(self.sequence_path)):
                msg = 'The sequence is outdated, consider refreshing it.'
                traceback[err_path+'outdated'] = msg

        return test, traceback

    def _pack_record(self, name, value, dtype):
        """
        packs awg_file record into a struct in the folowing way:
            struct.pack(fmtstring, namesize, datasize, name, data)
        where fmtstring = '<IIs"dtype"'

        The file record format is as follows:
        Record Name Size:        (32-bit unsigned integer)
        Record Data Size:        (32-bit unsigned integer)
        Record Name:             (ASCII) (Include NULL.)
        Record Data

        < denotes little-endian encoding, I and other dtypes are format
        characters denoted in the documentation of the struct package

        Args:
            name (str): Name of the record (Example: 'MAGIC' or
            'SAMPLING_RATE')
            value (Union[int, str]): The value of that record.
            dtype (str): String specifying the data type of the record.
                Allowed values: 'h', 'd', 's'.
        """
#        print(name)
#        print(value)
#        print(type(value))
#        print(dtype)
        if len(dtype) == 1:
            record_data = struct.pack('<' + dtype, value)
        else:
            if dtype[-1] == 's':
                record_data = value.encode('ASCII')
            else:
                record_data = struct.pack('<' + dtype, *value)

        # the zero byte at the end the record name is the "(Include NULL.)"
        record_name = name.encode('ASCII') + b'\x00'
        record_name_size = len(record_name)
        record_data_size = len(record_data)
        size_struct = struct.pack('<II', record_name_size, record_data_size)
        packed_record = size_struct + record_name + record_data

        return packed_record

    def generate_awg_file(self,
                          packed_waveforms, wfname_l, nrep, trig_wait,
                          goto_state, jump_to, channel_cfg):
        """
        This function generates an .awg-file for uploading to the AWG.
        The .awg-file contains a waveform list, full sequencing information
        and instrument configuration settings.

        Args:
            packed_waveforms (dict): dictionary containing packed waveforms
            with keys wfname_l

            wfname_l (numpy.ndarray): array of waveform names, e.g.
                array([[segm1_ch1,segm2_ch1..], [segm1_ch2,segm2_ch2..],...])

            nrep (list): list of len(segments) of integers specifying the
                no. of repetions per sequence element.
                Allowed values: 1 to 65536.

            trig_wait (list): list of len(segments) of integers specifying the
                trigger wait state of each sequence element.
                Allowed values: 0 (OFF) or 1 (ON).

            goto_state (list): list of len(segments) of integers specifying the
                goto state of each sequence element. Allowed values: 0 to 65536
                (0 means next)

            jump_to (list): list of len(segments) of integers specifying
                the logic jump state for each sequence element. Allowed values:
                0 (OFF) or 1 (ON).

            channel_cfg (dict): dictionary of valid channel configuration
                records.

        """

        timetuple = tuple(np.array(time.localtime())[[0, 1, 8, 2, 3, 4, 5, 6, 7]])

        # general settings
        head_str = BytesIO()
        bytes_to_write = (self._pack_record('MAGIC', 5000, 'h') +
                          self._pack_record('VERSION', 1, 'h'))
        head_str.write(bytes_to_write)

        sequence_cfg = {
            'SAMPLING_RATE': 1e9,
            'CLOCK_SOURCE': 1,
            'REFERENCE_SOURCE': 2,
            'EXTERNAL_REFERENCE_TYPE':  1,
            'REFERENCE_CLOCK_FREQUENCY_SELECTION': 1,
            'TRIGGER_SOURCE':   int(self.internal_trigger+1),
            'INTERNAL_TRIGGER_RATE': float(self.trigger_period)*1e-6,
            'TRIGGER_INPUT_IMPEDANCE': 1,
            'TRIGGER_INPUT_SLOPE': 1,
            'TRIGGER_INPUT_POLARITY': 1,
            'TRIGGER_INPUT_THRESHOLD':  1.4,
            'EVENT_INPUT_IMPEDANCE':   1,
            'EVENT_INPUT_POLARITY':  1,
            'EVENT_INPUT_THRESHOLD':   1.4,
            'JUMP_TIMING':   1,
            'RUN_MODE':   4,  # Continuous | Triggered | Gated | Sequence
            'RUN_STATE':  1,  # Off | On
        }

        for k in list(sequence_cfg.keys()):
            head_str.write(self._pack_record(k, sequence_cfg[k], self.driver.AWG_FILE_FORMAT_HEAD[k]))

        # channel settings
        ch_record_str = BytesIO()
        for k in list(channel_cfg.keys()):
            ch_k = k[:-1] + 'N'
            if ch_k in self.driver.AWG_FILE_FORMAT_CHANNEL:
                pack = self._pack_record(k, channel_cfg[k],
                                         self.driver.AWG_FILE_FORMAT_CHANNEL[ch_k])
                ch_record_str.write(pack)


        # waveforms
        ii = 21
        wf_record_str = BytesIO()
        wlist = list(packed_waveforms.keys())
        wlist.sort()
        for wf in wlist:
            wfdat = packed_waveforms[wf]
            lenwfdat = len(wfdat)
            wf_record_str.write(
                self._pack_record('WAVEFORM_NAME_{}'.format(ii), wf + '\x00',
                                  '{}s'.format(len(wf + '\x00'))) +
                self._pack_record('WAVEFORM_TYPE_{}'.format(ii), 1, 'h') +
                self._pack_record('WAVEFORM_LENGTH_{}'.format(ii),
                                  lenwfdat, 'l') +
                self._pack_record('WAVEFORM_TIMESTAMP_{}'.format(ii),
                                  timetuple[:-1], '8H') +
                self._pack_record('WAVEFORM_DATA_{}'.format(ii), wfdat,
                                  '{}H'.format(lenwfdat)))
            ii += 1
        # sequence
        seq_record_str = BytesIO()
        for i,t in enumerate(trig_wait):
            seq_record_str.write(
                self._pack_record('SEQUENCE_WAIT_{}'.format(i+1),
                                  trig_wait[i], 'h') +
                self._pack_record('SEQUENCE_LOOP_{}'.format(i+1),
                                  int(nrep[i]), 'l') +
                self._pack_record('SEQUENCE_JUMP_{}'.format(i+1),
                                  jump_to[i], 'h') +
                self._pack_record('SEQUENCE_GOTO_{}'.format(i+1),
                                  goto_state[i], 'h'))
            for ch_id in list(wfname_l.keys()):
                wfname = wfname_l[ch_id][i]
                seq_record_str.write(
                    self._pack_record('SEQUENCE_WAVEFORM_NAME_CH_' + str(ch_id)
                                      + '_{}'.format(i+1), wfname + '\x00',
                                      '{}s'.format(len(wfname + '\x00')))
                )

        awg_file = (head_str.getvalue() + ch_record_str.getvalue() +
                    wf_record_str.getvalue() + seq_record_str.getvalue())

        return awg_file


    def prepare_sequences(self, wait_trigger, start_with_event):
        seq = self.sequence
        context = seq.context

        packed_waveforms = {}
        wfname_l = {}
        nrep = []
        trig_wait = []
        goto_state = []
        jump_to = []
        
        loops = []
        name_parameters = []
        n_loops = len(self.parameters)
        
        first_index=1
        if n_loops>0:
            for params in self.parameters.items():
                loop_start = float(self.format_and_eval_string(params[1][0]))
                loop_stop = float(self.format_and_eval_string(params[1][1]))
                loop_points = int(self.format_and_eval_string(params[1][2]))
                loops.append(np.linspace(loop_start, loop_stop, loop_points))
                name_parameters.append(params[0])
                self.write_in_database(params[0]+'_loop', np.linspace(loop_start, loop_stop, loop_points))
            
            loop_values = np.moveaxis(np.array(np.meshgrid(*loops)),0,-1).reshape((-1,n_loops))
            self.write_in_database('num_loop', len(loop_values))
            
            for nn, loop_value in enumerate(loop_values):
                for ii, name_parameter in enumerate(name_parameters):
                    self.write_in_database(name_parameter, loop_value[ii])
                for k, v in self.sequence_vars.items():
                    seq.external_vars[k] = self.format_and_eval_string(v)
    #            context.sequence_name = '{}_{}'.format(seq_name_0, nn+1) #RL replaced, caused bug         
                context.sequence_name = '{}'.format(nn+first_index)
                res, byteseq, repeat, infos, errors = context.compile_loop(seq, for_file = True, factor=False)
                already_added = {}
                is_first_ch = True
                for ch_id in self.driver.defined_channels:
                    if ch_id in byteseq:
                        used_pos = []
                        for pos, waveform in enumerate(byteseq[ch_id]):
                            addr = id(waveform)
                            if addr not in already_added:
                                seq_name_transfered = context.sequence_name  + '_Ch{}'.format(ch_id) +\
                                                    '_' + str(pos)
                                packed_waveforms[seq_name_transfered] = waveform
                                already_added[addr] = seq_name_transfered
                            else:
                                seq_name_transfered =  already_added[addr]
    
                            if ch_id not in list(wfname_l.keys()):
                                wfname_l[ch_id] = [seq_name_transfered]
                            else:
                                wfname_l[ch_id].append(seq_name_transfered)
    
                            if (pos not in used_pos) and is_first_ch:
                                nrep.append(repeat[pos])
                                if  wait_trigger and used_pos == []:
                                    trig_wait.append(1)
                                else:
                                    trig_wait.append(0)
                                goto_state.append(0)
                                if start_with_event:
                                    jump_to.append(1)
                                else:
                                    jump_to.append(0)
                                used_pos.append(pos)
                        is_first_ch = False

        if start_with_event:
            trig_wait = [0] + trig_wait
            goto_state = [0] + goto_state
            jump_to = [2] + jump_to
            nrep = [0] + nrep
            for ch_id in byteseq:
                seq_name_standby = 'Standby_Ch{}'.format(ch_id)
                wfname_l[ch_id] = [seq_name_standby] + wfname_l[ch_id]
                packed_waveforms[seq_name_standby] = np.ones(256,dtype=np.uint16)*(2**13)
            goto_state[-1] = 2
        else:
            goto_state[-1] = 1

        if not res:
            raise Exception('Failed to compile sequence')

        for k, v in infos.items():
            self.write_in_database(k, v)
            
        return packed_waveforms, wfname_l, nrep, trig_wait, goto_state, jump_to

    def perform(self):
        """Compile the sequence.

        """
        channel_cfg = self.format_and_eval_string(self.awg_configuration)
#        print(channel_cfg)
        packed_waveforms, wfname_l, nrep, trig_wait, goto_state, \
                    jump_to = self.prepare_sequences(self.wait_trigger, 
                                                     self.start_with_event)

        awg_file = self.generate_awg_file(packed_waveforms, wfname_l, nrep,
                                          trig_wait, goto_state, jump_to, channel_cfg)

        self.driver.send_load_awg_file(awg_file)

        # Difficulty: the awg doesn't confirm the end of the loading
        timeout = 100
        start_time = time.clock()
        while time.clock()-start_time <= timeout:
            try:
                for ch_id in range(1,5):
                    if ch_id in list(wfname_l.keys()):
                        ch = self.driver.get_channel(ch_id)
                        ch.output_state = 'ON'
                break
            except:
                pass

    def register_preferences(self):
        """Register the task preferences into the preferences system.

        """
        super(TransferAWGFileTask, self).register_preferences()

        if self.sequence:
            self.preferences['sequence'] =\
                self.sequence.preferences_from_members()

    update_preferences_from_members = register_preferences

    def traverse(self, depth=-1):
        """Reimplemented to also yield the sequence

        """
        infos = super(TransferAWGFileTask, self).traverse(depth)

        for i in infos:
            yield i

        for item in self.sequence.traverse():
            yield item

    @classmethod
    def build_from_config(cls, config, dependencies):
        """Rebuild the task and the sequence from a config file.

        """
        builder = cls.mro()[1].build_from_config.__func__
        task = builder(cls, config, dependencies)

        if 'sequence' in config:
            pulse_dep = dependencies['exopy.pulses.item']
            builder = pulse_dep['exopy_pulses.RootSequence']
            conf = config['sequence']
            seq = builder.build_from_config(conf, dependencies)
            task.sequence = seq

        return task

    def _post_setattr_sequence(self, old, new):
        """Set up n observer on the sequence context to properly update the
        database entries.

        """
        entries = self.database_entries.copy()
        if old:
            old.unobserve('context', self._update_database_entries)
            if old.context:
                for k in old.context.list_sequence_infos():
                    del entries[k]
        if new:
            new.observe('context', self._update_database_entries)
            if new.context:
                entries.update(new.context.list_sequence_infos())

        if entries != self.database_entries:
            self.database_entries = entries
            
    def _post_setattr_parameters(self, old, new):
        """Observer keeping the database entries in sync with the declared
        definitions.

        """
        entries = self.database_entries.copy()
        for e in old:
            del entries[e]
            del entries[e+'_loop']
        for e in new:
            entries.update({key: 0.0 for key in new})
            entries.update({key+'_loop': 0.0 for key in new})
        self.database_entries = entries
        
    def _update_database_entries(self, change):
        """Reflect in the database the sequence infos of the context.

        """
        entries = self.database_entries.copy()
        if change.get('oldvalue'):
            for k in change['oldvalue'].list_sequence_infos():
                del entries[k]
        if change['value']:
            context = change['value']
            entries.update(context.list_sequence_infos())

        self.database_entries = entries
