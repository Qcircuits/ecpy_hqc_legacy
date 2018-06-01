# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright 2015-2017 by ExopyHqcLegacy Authors, see AUTHORS for more details.
#
# Distributed under the terms of the BSD license.
#
# The full license is in the file LICENCE, distributed with this software.
# -----------------------------------------------------------------------------
"""Tasks to operate on numpy.arrays.

"""
import numpy as np
from atom.api import (Enum, Bool, Unicode, set_default, Float, Int)
from scipy.interpolate import splrep, sproot, splev
from scipy.optimize import curve_fit, leastsq
import scipy.ndimage.filters as flt
import matplotlib.pyplot as plt
import scipy

import logging
from exopy.tasks.api import SimpleTask, InterfaceableTaskMixin, TaskInterface
from exopy.tasks.api import validators

ARR_VAL = validators.Feval(types=np.ndarray)


class ThresholdIQTask(SimpleTask):
    """ Store the pair(s) of index/value for the extrema(s) of an array.

    Wait for any parallel operation before execution.

    """
    #: Name of the target in the database.
    target_array_I = Unicode().tag(pref=True)
    target_array_Q = Unicode().tag(pref=True)

    
    #: Value of theta for IQ rotation
    theta = Unicode().tag(pref=True)
    
    #: Value of threshold once rotated
    thresh = Unicode().tag(pref=True)
    
    #: Min histogram value
    min_hist = Unicode().tag(pref=True)
    
    #: Max histogram value
    max_hist = Unicode().tag(pref=True)

    #: Nb bin in histogram
    bin_hist = Unicode('20').tag(pref=True)
    

    database_entries = set_default({'I': np.array([1.0]), 'Q': np.array([1.0]),
                                    'bit': np.array([1.0]), 
                                    'hist':np.array([1.0]), 
                                    'hist_axis': np.array([1.0])})
    
    wait = set_default({'activated': True})  # Wait on all pools by default.

    def perform(self):
        """ Find extrema of database array and store index/value pairs.

        """
        array_I = self.format_and_eval_string(self.target_array_I)
        array_Q = self.format_and_eval_string(self.target_array_Q)
        thresh = self.format_and_eval_string(self.thresh)
        theta = self.format_and_eval_string(self.theta)
        bin_hist = self.format_and_eval_string(self.bin_hist)
        min_hist = self.format_and_eval_string(self.min_hist)
        max_hist = self.format_and_eval_string(self.max_hist)
        shape_data = array_I.shape
        # shape[0] = nb of points for statistics, typic. 1000
        # shape[1] = nb of sequences if AWG in sequence mode
        
        array_I_flat = array_I.flatten()
        array_Q_flat = array_Q.flatten()
        array_c = array_I_flat + 1j*array_Q_flat
                
#        theta = IQ_rotate(array_I_flat, array_Q_flat)
        array_c_rot = array_c*np.exp(1j*theta)
        
        array_I = np.real(array_c_rot).reshape(shape_data)
        array_Q = np.imag(array_c_rot).reshape(shape_data)
        
        array_bit = array_I>thresh
        
        hists = []
        for seq in range(shape_data[-1]):
            hist, bin_edges = np.histogram(array_I[:, seq], bins=bin_hist, range=(min_hist, max_hist))
            hists.append(hist)
            
        hists = np.array(hists).T
        hist_axis = bin_edges[:-1]+(bin_edges[1]-bin_edges[0])/2

        self.write_in_database('bit', array_bit)
        self.write_in_database('hist', hists)
        self.write_in_database('hist_axis', hist_axis)
        self.write_in_database('I', array_I)
        self.write_in_database('Q', array_Q)

    def check(self, *args, **kwargs):
        """ Check the target array can be found and has the right column.

        """
        test, traceback = super(ThresholdIQTask, self).check(*args, **kwargs)

        if not test:
            return test, traceback
#        array = self.format_and_eval_string(self.target_array)
#        print(self.target_array)
#        print(array)
#        print('blaaaaah')
#        err_path = self.get_error_path()
#
#        if self.column_name:
#            if array.dtype.names:
#                names = array.dtype.names
#                if self.column_name not in names:
#                    msg = 'No column named {} in array. (column are : {})'
#                    traceback[err_path] = msg.format(self.column_name, names)
#                    return False, traceback
#            else:
#                traceback[err_path] = 'Array has no named columns'
#                return False, traceback
#
#        else:
#            if array.dtype.names:
#                msg = 'The target array has names columns : {}. Choose one'
#                traceback[err_path] = msg.format(array.dtype.names)
#                return False, traceback
#            elif len(array.shape) > 1:
#                msg = 'Must use 1d array when using non record arrays.'
#                traceback[err_path] = msg
#                return False, traceback

        return test, traceback

#    def _post_setattr_mode(self, old, new):
#        """ Update the database entries according to the mode.
#
#        """
#        if new == 'Max':
#            self.database_entries = {'I': 0, 'Q': 2.0}
#        else:
#            self.database_entries = {'I': 0, 'Q': 1.0}

def _find_weights(x, x_ref):
    '''
    Inputs
    ------
    x(float):x_value we want to bound by 2 x_refs values
    x_ref(array)

    Outputs:
    --------
    indices(int): indices of bounds in x_ref
    weights(list): weights of either bound

    '''
    if x>np.max(x_ref) or x<np.min(x_ref):
        raise ValueError('Searched value should be in the bound of the search array')
    i0 = np.argmin(np.abs(x_ref-x))
    x0_ref = x_ref[i0]

    if x>=x0_ref and x0_ref != np.max(x_ref):
        i1 = i0+1
        x1_ref = x_ref[i1]
    else:
        i1 = i0
        x1_ref = x0_ref
        i0 = i0-1
        x0_ref = x_ref[i0]

    delta_x = x1_ref-x0_ref
    weight_x0 = 1-(x-x0_ref)/delta_x
    weight_x1 = 1-(-x+x1_ref)/delta_x

    return(i0,i1, weight_x0, weight_x1)


def adapt_ref(x_data, x_ref, maglin_ref, phase_ref):
    '''
    If x_data and x_ref are not the same, interpolate the data_ref to match
    the data linspace.

    Inputs
    ------
    x_data(array): data to be fitter
    x_ref(array): ref support (e.g. spec frequecies)
    maglin_ref(array): data_ref
    phase_ref(array): data_ref

    Outputs:
    --------
    adapted x_ref(array), maglin_ref(array) and phase_ref(array)

    '''
    data_c_ref =  maglin_ref*np.exp(1j*np.pi/180*phase_ref)
    X = len(x_data)
    maglin_ref_adapted = np.empty(X)
    phase_ref_adapted = np.empty(X)
    for ii, x in enumerate(x_data):
        i0, i1, w0, w1 = _find_weights(x, x_ref)
        data_c_calc = data_c_ref[i0]*w0+data_c_ref[i1]*w1
        maglin_ref_adapted[ii] = np.abs(data_c_calc)
        phase_ref_adapted[ii] = 180/np.pi*np.angle(data_c_calc)
    return(x_data, maglin_ref_adapted, phase_ref_adapted)


def complex_fit(f, xData, yData, p0, weights=None, bounds=()):
    if np.isscalar(p0):
        p0 = np.array([p0])

    def residuals(params, x, y):
        if weights is not None:
            diff = weights * f(x, *params) - y
        else:
            diff = f(x, *params) - y
        flatDiff = np.zeros(diff.size * 2, dtype=np.float64)
        flatDiff[0:flatDiff.size:2] = diff.real
        flatDiff[1:flatDiff.size:2] = diff.imag
        return flatDiff

    res = leastsq(residuals, p0, args=(xData, yData), maxfev=1000,
                  ftol=1e-2, full_output=1)
    return res[0], res[1]


def complex_a_out(f, f_0, kc, ki, a_in, T):  # kc and ki are kappas/2pi
    D = f - f_0
    num = - 1j*D + (kc - ki)/2
    den = 1j*D + (kc+ki)/2
    if kc > 0 and ki > 0 and f_0 > 0:
        return num/den*a_in*np.exp(1j*D*T)
    else:
        return np.Inf


def fit_complex_a_out(f, a_out):
    f_0, kc = get_f0_reflection(f, a_out)
    kc = 10e6
    ki = kc
    T = 0

#    plt.close('all')
#    fig, ax = plt.subplots(3)
#    ax[0].scatter(f, np.abs(a_out))
#    ax[1].scatter(f, np.angle(a_out))
#    ax[0].plot([f_0, f_0], [min(np.abs(a_out)), max(np.abs(a_out))])
#    ax[0].plot([f_0-kc, f_0+kc], [max(np.abs(a_out)), max(np.abs(a_out))])
#    ax[2].scatter(np.real(a_out), np.imag(a_out))
#    ax[2].axis('equal')
#    plt.show()

    def aux(f, f_0, kc, ki, re_a_in, im_a_in, T):
        return complex_a_out(f, f_0, kc, ki, re_a_in + 1j*im_a_in, T)
    a_in = -a_out[0]
    popt, pcov = complex_fit(aux, f, a_out, (f_0, kc, ki, np.real(a_in),
                                             np.imag(a_in), T))
    fit_error = 100*np.sqrt(pcov[0, 0])/popt[0]

#    print(popt)

#    a_out_fit = complex_a_out(f, *popt)
#    ax[0].plot(f, np.abs(a_out_fit))
#    ax[1].plot(f, np.angle(a_out_fit))
#
    return popt[0], fit_error


def get_f0_reflection(f, a_out):
    phase = np.unwrap(np.angle(a_out))
    phase_avg = (np.min(phase)+np.max(phase))/2
    spline = splrep(f, phase-phase_avg)
    roots = sproot(spline)
    if len(roots) != 1:
        maglin = np.abs(a_out)
        f0 = f[np.argmin(maglin)]
    else:
        f0 = roots[0]

    phase_flt = flt.gaussian_filter(phase, 1)
    dphase_flt = np.diff(phase_flt)
    df = f[:-1]
    spline = splrep(df, dphase_flt-(max(dphase_flt)+min(dphase_flt))/2)
    roots = sproot(spline)
    kc = roots[-1]-roots[0]
    return f0, kc


def lorentzian(x, x0, y0, A, B):
    numerator = A
    denominator = (x - x0)**2 + B
    y = y0 + (numerator/denominator)
    return y


def fit_lorentzian(x, y, error=None):
    if error is not None:
        for ii in range(len(y)):
            if error[ii] > 1:
                y[ii] = y[ii-1]

    ymean = np.mean(y)
    ymax = np.amax(y)
    ymin = np.amin(y)
    if ymean < (ymax+ymin)/2:
        index = np.argmax(y)
#        print(index)
        y0 = ymin
    else:
        ymax = ymin
        index = np.argmin(y)
        y0 = ymax
    x0 = x[index]
    spline = splrep(x, y-(y0+ymax)/2)
    roots = sproot(spline)
    whm = roots[-1]-roots[0]

    B = whm*whm/4.0
    A = B*(ymax-y0)
    popt, pcov = curve_fit(lorentzian, x, y, (x0, y0, A, B))
    fit_error = 100*np.sqrt(pcov[0, 0])/popt[0]

#    plt.close('all')
#    fig, ax = plt.subplots()
#    ax.scatter(x, y)
#    ax.plot(x, lorentzian(x, *popt))
#    ax.plot([min(x), max(x)], [y0, y0])
#    ax.plot([min(x), max(x)], [ymax, ymax])
#    ax.plot([x0, x0], [y0, ymax])
#    plt.show()
#    print(popt)
    return popt[0], fit_error

def IQ_rotate(I, Q):
        Cov=np.cov(I,Q)
        A=scipy.linalg.eig(Cov)
        eigvecs=A[1]
        if A[0][1]>A[0][0]:
            eigvec1=eigvecs[:,0]
        else:
            eigvec1=eigvecs[:,1]
        theta=np.arctan(eigvec1[0]/eigvec1[1])
        return theta
