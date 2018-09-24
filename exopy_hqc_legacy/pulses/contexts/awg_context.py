# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright 2015-2018 by ExopyPulses Authors, see AUTHORS for more details.
#
# Distributed under the terms of the BSD license.
#
# The full license is in the file LICENCE, distributed with this software.
# -----------------------------------------------------------------------------
"""Context compiling sequences for the Tektronix AWG5014.

"""
import numpy as np
from atom.api import Unicode, Float, Bool, set_default

from exopy_pulses.pulses.api import BaseContext, TIME_CONVERSION

to_bytes = np.ndarray.tobytes


class AWG5014Context(BaseContext):
    """Context compiling sequences for the Tektronix AWG5014.

    """
    #: Generic name used when storing the sequence on the instrument.
    #: The channel name (Ch1, Ch2, ...) will be appended to it when
    #: transferring.
    sequence_name = Unicode().tag(pref=True, fmt=False)

    #: Sampling frequency in Hz
    sampling_frequency = Float(1e9).tag(pref=True)

    #: Should the transferred sequences be selected on the matching channels.
    select_after_transfer = Bool(True).tag(pref=True)

    #: Should the unused channels be cleared (to avoid attempting to play an
    #: old sequence).
    clear_unused_channels = Bool(True).tag(pref=True)

    #: Should the instrument be made to run the sequences after a successful
    #: transfer.
    run_after_transfer = Bool(True).tag(pref=True)

    time_unit = set_default('mus')

    analogical_channels = set_default(('Ch1_A', 'Ch2_A', 'Ch3_A', 'Ch4_A'))

    logical_channels = set_default(('Ch1_M1', 'Ch2_M1', 'Ch3_M1', 'Ch4_M1',
                                    'Ch1_M2', 'Ch2_M2', 'Ch3_M2', 'Ch4_M2'))

    def compile_and_transfer_sequence(self, sequence, driver=None):
        """Compile the pulse sequence and send it to the instruments.

        As this context does not support any special sequence it will always
        get a flat list of pulses.

        Parameters
        ----------
        sequence : RootSequence
            Sequence to compile and transfer.

        driver : object, optional
            Instrument driver to use to transfer the sequence once compiled.
            If absent the context should do its best to assert that the
            compilation can succeed.

        Returns
        -------
        result : bool
            Whether the compilation succeeded.

        infos : dict
            Infos about the transferred and compiled sequence. The keys
            should match the ones listed in sequence_infos_keys.

        errors : dict
            Errors that occured during compilation.

        """
        items, errors = self.preprocess_sequence(sequence)

        if errors:
            return False, {}, errors

        duration = max([pulse.stop for pulse in items])
        if sequence.time_constrained:
            # Total length of the sequence to send to the AWG
            duration = sequence.duration

        # Collect the channels used in the pulses' sequence
        used_channels = set([pulse.channel[:3] for pulse in items])

        # Coefficient to convert the start and stop of pulses in second and
        # then in index integer for array
        time_to_index = TIME_CONVERSION[self.time_unit]['s'] * \
            self.sampling_frequency

        # Length of the sequence
        sequence_length = int(round(duration * time_to_index))

        # create 3 array for each used_channels
        array_analog = {}
        array_M1 = {}
        array_M2 = {}
        for channel in used_channels:
            # numpy array for analog channels int16 init 2**13
            array_analog[channel] = np.ones(sequence_length,
                                            dtype=np.uint16)*(2**13)
            # numpy array for marker1 init False. For AWG M1 = 0 = off
            array_M1[channel] = np.zeros(sequence_length, dtype=np.int8)
            # numpy array for marker2 init False. For AWG M2 = 0 = off
            array_M2[channel] = np.zeros(sequence_length, dtype=np.int8)

        for pulse in [i for i in items if i.duration != 0.0]:

            waveform = pulse.waveform
            channel = pulse.channel[:3]
            channeltype = pulse.channel[4:]

            start_index = int(round(pulse.start*time_to_index))
            stop_index = start_index + len(waveform)

            if channeltype == 'A' and pulse.kind == 'Analogical':
                array_analog[channel][start_index:stop_index] +=\
                    np.require(np.rint(8191*waveform), np.uint16)
            elif channeltype == 'M1' and pulse.kind == 'Logical':
                array_M1[channel][start_index:stop_index] += waveform
            elif channeltype == 'M2' and pulse.kind == 'Logical':
                array_M2[channel][start_index:stop_index] += waveform
            else:
                msg = 'Selected channel does not match kind for pulse {} ({}).'
                return (False, dict(),
                        {'Kind issue': msg.format(pulse.index,
                                                  (pulse.kind, pulse.channel))}
                        )

        # Check the overflows
        traceback = {}
        for channel in used_channels:
            analog = array_analog[channel]
            if analog.max() > 16383 or analog.min() < 0:
                mes = 'Analogical values out of range.'
                traceback['{}_A'.format(channel)] = mes

            elif array_M1[channel].max() > 1 or array_M1[channel].min() < 0:
                mes = 'Overflow in marker 1.'
                traceback['{}_M1'.format(channel)] = mes

            elif array_M2[channel].max() > 1 or array_M2[channel].min() < 0:
                mes = 'Overflow in marker 2.'
                traceback['{}_M2'.format(channel)] = mes

        if traceback:
            return False, dict(), traceback

        # Invert marked logical channels.
        for i_ch in self.inverted_log_channels:
            ch, m = i_ch.split('_')
            if m == 'M1':
                np.logical_not(array_M1[ch], array_M1[ch])
            else:
                np.logical_not(array_M2[ch], array_M2[ch])

        # Byte arrays to send to the AWG
        to_send = {}
        for channel in used_channels:
            # Convert to sixteen bits integers
            array = array_analog[channel] +\
                array_M1[channel]*(2**14) + array_M2[channel]*(2**15)
            # Creating and filling a byte array for each channel.
            aux = np.empty(2*len(array), dtype=np.uint8)
            aux[::2] = array % 2**8
            aux[1::2] = array // 2**8
            to_send[int(channel[-1])] = bytearray(aux)
            
        # Build sequence infos
        name = self._cache['sequence_name']
        infos = dict(sampling_frequency=self.sampling_frequency,
                     sequence_ch1='',
                     sequence_ch2='',
                     sequence_ch3='',
                     sequence_ch4='')
        for c in used_channels:
            infos['sequence_ch%s' % c[2]] = name + '_' + c

        # In the absence of a driver we stop here
        if not driver:
            return True, infos, traceback

        # If we do have a driver proceed to the transfer.
        return self._transfer_sequences(driver, to_send, infos)

    def merge_intervals(self, intervals, sequence_length):
        """ XXX a docstring is really needed here and some comments in
        particular on the nested while.

        """
        if intervals[0][0] <= 256:
            intervals[0] = (1, intervals[0][1])

        for i, interval in enumerate(intervals):
            if interval[1] - interval[0] < 256:
                if interval[0] + 256 >= sequence_length:
                    intervals[i] = (interval[1] - 256, interval[1])
                else:
                    intervals[i] = (interval[0], interval[0]+256)
        i = 1
        while i < len(intervals):
            while (i < len(intervals) and
                   intervals[i][0] - intervals[i-1][1] < 256):
                intervals[i-1] = (intervals[i-1][0], max(intervals[i][1],
                                  intervals[i-1][1]))
                del intervals[i]
            i += 1

        if sequence_length - intervals[-1][1] < 256:
            intervals[-1] = (intervals[-1][0], sequence_length + 1)

    def compile_loop(self, sequence, for_file=False, factor=True, **kwargs):
        """ Transform a sequence of pulse to a dict of waveform suitable for
        sequence mode of the AWG

        Parameters
        ----------
        pulses : list(Pulse)
            List of pulse generated by the compilation of a sequence.

        Returns
        -------
        result : bool
            Boolean indicating whether or not the compilation succeeded.

        to_send or traceback : dict
            Dict of {channel: array of (bytearrays,intarray,intarray)} to send
            to the AWG in case of success containing waveform, position(s) and
            repeat(s) or the traceback of the issues in case of failure.


        """
        items, errors = self.preprocess_sequence(sequence)

        if errors:
            return False, {}, errors

        duration = max([pulse.stop for pulse in items])
        if sequence.time_constrained:
            # Total length of the sequence to send to the AWG
            duration = sequence.duration

        # Collect the channels used in the pulses' sequence
        used_channels = set([pulse.channel[:3] for pulse in items])

        # Coefficient to convert the start and stop of pulses in second and
        # then in index integer for array
        time_to_index = TIME_CONVERSION[self.time_unit]['s'] * \
            self.sampling_frequency

        # Length of the sequence
        sequence_length = int(round(duration * time_to_index))

        # make zero space a multiple repeat of 256 zero samples
        zero_length = 256
        azeros = np.ones(zero_length, dtype=np.uint16)*(2**13)
        mzeros = np.zeros(zero_length, dtype=np.int8)
        array_analog = {}
        array_M1 = {}
        array_M2 = {}
        repeats = []
        for channel in used_channels:
            array_analog[channel] = []
            array_M1[channel] = []
            array_M2[channel] = []
        intervals_to_pulses_a = {}
        intervals_to_pulses_m1 = {}
        intervals_to_pulses_m2 = {}
        for channel in used_channels:
            intervals_to_pulses_a[channel] = {}
            intervals_to_pulses_m1[channel] = {}
            intervals_to_pulses_m2[channel] = {}
            
        if factor:
            # intervals are places that have pulses on at least one  channel
            intervals = []
            for pulse in [i for i in items if i.duration != 0.0]:
    
                waveform = pulse.waveform
                start_index = int(round(pulse.start*time_to_index))
                stop_index = start_index + len(waveform)
                intervals.append((start_index, stop_index))
            # sort and merge intervals
            # XXX this is mostly duplicated and should be refactored
            intervals.sort()
            i = 1
            while i < len(intervals):
                while i < len(intervals) and intervals[i][0] < intervals[i-1][1]:
                    newlast = intervals[i][1]
                    del intervals[i]
                    intervals[i-1] = (intervals[i-1][0],
                                      max(newlast, intervals[i-1][1]))
                i += 1
                
            # check that the minimum length of the each pulse and space between
            # them are > 256 samples fix if the condition is not satisfied
            self.merge_intervals(intervals, sequence_length)
            
            # fill up the space between start of sequence and first sample of pulse
            #  with zero samples
            if intervals[0][0] != 1:
                zcount = int((intervals[0][0] - 1) / zero_length) - 1
                zrem = zero_length + (intervals[0][0] - 1) % zero_length
                azrem = np.ones(zrem, dtype=np.uint16)*(2**13)
                mzrem = np.zeros(zrem, dtype=np.int8)
                if zcount > 0:
                    repeats.append(zcount)
                repeats.append(1)
                for channel in used_channels:
                    if zcount > 0:
                        array_analog[channel].append(azeros)
                        array_M1[channel].append(mzeros)
                        array_M2[channel].append(mzeros)
                    array_analog[channel].append(azrem)
                    array_M1[channel].append(mzrem)
                    array_M2[channel].append(mzrem)
            
            for idx, interval in enumerate(intervals):
                for channel in used_channels:
                    afill = 2**13*np.ones(interval[1] - interval[0],
                                          dtype=np.uint16)
                    mfill1 = np.zeros(interval[1] - interval[0], dtype=np.int8)
                    mfill2 = np.zeros(interval[1] - interval[0], dtype=np.int8)
                    array_analog[channel].append(afill)
                    array_M1[channel].append(mfill1)
                    array_M2[channel].append(mfill2)
                    intervals_to_pulses_a[channel][interval] = afill
                    intervals_to_pulses_m1[channel][interval] = mfill1
                    intervals_to_pulses_m2[channel][interval] = mfill2
                    
                remaining = 0
                if idx + 1 == len(intervals):
                    remaining = sequence_length - interval[1] + 1
                else:
                    remaining = intervals[idx+1][0] - intervals[idx][1]
                zcount = int(remaining / zero_length) - 1
                zrem = zero_length + remaining % zero_length
                azrem = np.ones(zrem, dtype=np.uint16)*(2**13)
                mzrem = np.zeros(zrem, dtype=np.int8)
                repeats.append(1)
                if zcount > 0:
                    repeats.append(zcount)
                repeats.append(1)
    
                if remaining != 0:
                    for channel in used_channels:
                        if zcount > 0:
                            array_analog[channel].append(azeros)
                            array_M1[channel].append(mzeros)
                            array_M2[channel].append(mzeros)
                        array_analog[channel].append(azrem)
                        array_M1[channel].append(mzrem)
                        array_M2[channel].append(mzrem)
        else:
            start_index = 0
            stop_index = sequence_length
            intervals = [(start_index, stop_index)]
            for channel in used_channels:
                a_fill = np.ones(sequence_length, dtype=np.uint16)*(2**13)
                m1_fill = np.zeros(sequence_length, dtype=np.int8)
                m2_fill = np.zeros(sequence_length, dtype=np.int8)
                array_analog[channel].append(a_fill)
                array_M1[channel].append(m1_fill)
                array_M2[channel].append(m2_fill)
                intervals_to_pulses_a[channel][intervals[0]]=a_fill
                intervals_to_pulses_m1[channel][intervals[0]]=m1_fill
                intervals_to_pulses_m2[channel][intervals[0]]=m2_fill
            repeats = [1]
            
        for pulse in [i for i in items if i.duration != 0.0]:
            waveform = pulse.waveform
            channel = pulse.channel[:3]
            channeltype = pulse.channel[4:]

            start_index = int(round(pulse.start*time_to_index))
            stop_index = start_index + len(waveform)

            interval_i = 0
            while intervals[interval_i][1] < start_index:
                interval_i += 1
            interval = intervals[interval_i]

            wav_slice = slice(start_index - interval[0],
                              stop_index - interval[0])
            if channeltype == 'A' and pulse.kind == 'Analogical':
                intervals_to_pulses_a[channel][interval][wav_slice] +=\
                    (np.rint(8191*waveform)).astype(np.uint16)
            elif channeltype == 'M1' and pulse.kind == 'Logical':
                intervals_to_pulses_m1[channel][interval][wav_slice] +=\
                    waveform
            elif channeltype == 'M2' and pulse.kind == 'Logical':
                intervals_to_pulses_m2[channel][interval][wav_slice] +=\
                    waveform
            else:
                msg = 'Selected channel does not match kind for pulse {} ({}).'
                return (False, None, None, dict(),
                        {'Kind issue': msg.format(pulse.index,
                                                  (pulse.kind, pulse.channel))}
                        )

        # Check the overflows
        traceback = {}
        for channel in used_channels:
            for i in range(len(array_analog[channel])):
                analog = array_analog[channel][i]
                m1 = array_M1[channel][i]
                m2 = array_M2[channel][i]
                if analog.max() > 16383 or analog.min() < 0:
                    mes = 'Analogical values out of range.'
                    traceback['{}_A'.format(channel)] = mes

                elif m1.max() > 1 or m1.min() < 0:
                    mes = 'Overflow in marker 1.'
                    traceback['{}_M1'.format(channel)] = mes

                elif m2.max() > 1 or m2.min() < 0:
                    mes = 'Overflow in marker 2.'
                    traceback['{}_M2'.format(channel)] = mes

        if traceback:
            return False, None, None, dict(), traceback

        # Invert marked logical channels.
        for i_ch in self.inverted_log_channels:
            ch, m = i_ch.split('_')
            if m == 'M1':
                for waveform in array_M1[ch]:
                    np.logical_not(waveform, waveform)
            else:
                for waveform in array_M2[ch]:
                    np.logical_not(waveform, waveform)

        # Byte arrays to send to the AWG
        wfs = {}
        already_added = {}
        for channel in used_channels:
            wfs[int(channel[-1])] = []
            for i in range(len(array_analog[channel])):
                addr = id(array_analog[channel][i])
                if addr in already_added:
                    added = already_added[addr]
                    wfs[int(channel[-1])].append(added)

                else:
                    waveform_new = (array_analog[channel][i] +
                                    array_M1[channel][i]*(2**14) +
                                    array_M2[channel][i]*(2**15))
                    aux = np.empty(2*len(waveform_new), dtype=np.uint8)
                    if for_file:
                        wfadded = waveform_new
                    else:
                        aux[::2] = waveform_new % 2**8
                        aux[1::2] = waveform_new // 2**8
                        wfadded = bytearray(aux)
                    wfs[int(channel[-1])].append(wfadded)
                    already_added[addr] = wfadded

        # Build sequence infos
        name = self._cache['sequence_name']
        infos = dict(sampling_frequency=self.sampling_frequency,
                     sequence_ch1='',
                     sequence_ch2='',
                     sequence_ch3='',
                     sequence_ch4='')
        for c in used_channels:
            infos['sequence_ch%s' % c[2]] = name + '_' + c
#        print(len(repeats))
#        print(repeats[:10])
        return True, wfs, repeats, infos, traceback


    def list_sequence_infos(self):
        """List the sequence infos returned after a successful completion.

        Returns
        -------
        infos : dict
            Dict mimicking the one returned on successful completion of
            a compilation and transfer. The values types should match the
            the ones found in the real infos.

        """
        return dict(sampling_frequency=1e9,
                    sequence_ch1='Seq_Ch1',
                    sequence_ch2='Seq_Ch2',
                    sequence_ch3='Seq_Ch3',
                    sequence_ch4='Seq_Ch4')

    # =========================================================================
    # --- Private API ---------------------------------------------------------
    # =========================================================================

    def _transfer_sequences(self, driver, sequences, infos):
        """Transfer a previously compiled sequence.

        """
        for ch_id in driver.defined_channels:
            if ch_id in sequences:
                driver.to_send(infos['sequence_ch%s' % ch_id],
                               sequences[ch_id])

        if self.select_after_transfer:
            driver.sampling_frequency = self.sampling_frequency
            for ch_id in driver.defined_channels:
                ch = driver.get_channel(ch_id)
                if ch_id in sequences:
                    ch.select_sequence(infos['sequence_ch%s' % ch_id])
                elif self.clear_unused_channels:
                    ch.clear_sequence()

        if self.run_after_transfer:
            for ch_id in sequences:
                ch = driver.get_channel(ch_id)
                ch.output_state = 'ON'
            driver.running = True

        return True, infos, {}

    def _get_sampling_time(self):
        """Getter for the sampling time prop of BaseContext.

        """
        return 1/self.sampling_frequency*TIME_CONVERSION['s'][self.time_unit]

    def _post_setattr_time_unit(self, old, new):
        """Reset sampling time as the conversion changed.

        """
        self._reset_sampling_time()

    def _post_setattr_sampling_frequency(self, old, new):
        """Reset sampling when the frequency change.

        """
        self._reset_sampling_time()

    def _reset_sampling_time(self):
        """Reset the sampling_time property.

        """
        member = self.get_member(str('sampling_time'))  # HINT C API
        member.reset(self)
