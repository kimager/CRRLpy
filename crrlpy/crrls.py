#!/usr/bin/env python
from __future__ import division

import os
import re

import matplotlib as mpl
havedisplay = "DISPLAY" in os.environ
if not havedisplay:
    mpl.use('Agg')
import numpy as np

from scipy import interpolate
from scipy.special import wofz
from astropy.constants import c, k_B

from crrlpy import utils
from crrlpy.frec_calc import set_dn, make_line_list

def alphanum_key(s):
    """ 
    Turn a string into a list of string and number chunks.
    
    :param s: String
    :returns: List with strings and integers.
    :rtype: list
    
    :Example:
    
    >>> alphanum_key('z23a')
    ['z', 23, 'a']
    
    """
    return [ tryint(c) for c in re.split('([0-9]+)', s) ]

def average(data, axis, n):
    """
    Averages data along the given axis by combining n adjacent values.
    
    :param data: Data to average along a given axis.
    :type data: numpy array
    :param axis: Axis along which to average.
    :type axis: int
    :param n: Factor by which to average.
    :type n: int
    :returns: Data decimated by a factor n along the given axis.
    :rtype: numpy array
    """
    
    swpdata = np.swapaxes(data, 0, axis)
    
    if n < 1:
        print("Will not work")
        avg_tmp = swpdata
    else:
        avg_tmp = 0
        for i in xrange(n):
            si = (n - 1) - i
            if si <= 0:
                avg_tmp += swpdata[i::n]
            else:
                avg_tmp += swpdata[i:-si:n]
        avg_tmp = avg_tmp/n
        
    return np.swapaxes(avg_tmp, axis, 0)


def blank_lines(freq, tau, reffreqs, v0, dv):
    """
    Blanks the lines in a spectra.
    
    :param freq: Frequency axis of the spectra.
    :type freq: array, MHz
    :param tau: Optical depth axis of the spectra.
    :type tau: array
    :param reffreqs: List with the reference frequency of the lines. Should be the rest frequency.
    :type reffreqs: list
    :param v0: Velocity shift to apply to the lines defined by `reffreq`. (km/s)
    :type v0: float
    :param dv: Velocity range to blank around the lines. (km/s)
    :type dv: float
    """
    
    try:
        for ref in reffreqs:
            #print "#freq: {0} #tau: {1}".format(len(freq), len(tau))
            lm0, lmf = get_line_mask(freq, ref, v0, dv0)
            freq = np.concatenate((freq[:lm0], freq[lmf:]))
            tau = np.concatenate((tau[:lm0], tau[lmf:]))
    except TypeError:
        lm0, lmf = get_line_mask(freq, reffreqs, v0, dv0)
        freq = np.concatenate((freq[:lm0], freq[lmf:]))
        tau = np.concatenate((tau[:lm0], tau[lmf:]))
        
    return freq, tau


def blank_lines2(freq, tau, reffreqs, dv):
    """
    Blanks the lines in a spectra. 
    
    :param freq: Frequency axis of the spectra. (MHz)
    :type freq: array
    :param tau: Optical depth axis of the spectra.
    :type tau: array
    :param reffreqs: List with the reference frequency of the lines. Should be the rest frequency.
    :type reffreqs: list
    :param dv: Velocity range to blank around the lines. (km/s)
    :type dv: float
    """
    
    try:
        for ref in reffreqs:
            #print "#freq: {0} #tau: {1}".format(len(freq), len(tau))
            #print "reffreq: {0}".format(ref)
            lm0, lmf = get_line_mask2(freq, ref, dv)
            freq = np.concatenate((freq[:lm0], freq[lmf:]))
            tau = np.concatenate((tau[:lm0], tau[lmf:]))
    except TypeError:
        lm0, lmf = get_line_mask2(freq, reffreqs, dv)
        freq = np.concatenate((freq[:lm0], freq[lmf:]))
        tau = np.concatenate((tau[:lm0], tau[lmf:]))
        
    return freq, tau


def df2dv(f0, df):
    """
    Convert a frequency delta to a velocity delta given a central frequency.
    
    :param f0: Rest frequency.
    :type f0: float
    :param df: Frequency delta.
    :type df: float
    :returns: The equivalent velocity delta for the given frequency delta.
    :rtype: float in :math:`\mbox{m s}^{-1}`
    """
    
    return c.to('m/s').value*(df/f0)


def doppler_broad(t, m, vrms, fwhm=False):
    """
    Doppler broadening.
    
    :math:`\\frac{\Delta v}{\mbox{m s}^{-1}}=(\\frac{2k_{B}T}{m}+v_{\mathrm{rms}}^2)^{1/2}`
    
    :param t: Gas temperature in K.
    :type t: float
    :param m: Mass of the element producing the line in amu.
    :type m: float
    :param vrms: Turbulent velocity in :math:`\mbox{m s}^{-1}`.
    :type vrms: float
    :returns: The sigma or FWHM of a Gaussian line due to Doppler broadening in :math:`\mbox{m s}^{-1}`.
    :rtype: float
    """

    dv = np.sqrt(8314.46262103*t/m + np.power(vrms, 2.))
    
    if fwhm:
        dv = sigma2fwhm(dv)
    
    return dv


def doppler_temp(sigma, m, vrms, fwhm=False):
    """
    The temperature required to produce a Gaussian line of width sigma.
    
    :param sigma: The sigma or FWHM of a Gaussian line due to Doppler broadening in :math:`\mbox{m s}^{-1}`.
    :type sigma: float
    :param m: Mass of the element producing the line in amu.
    :type m: float
    :param vrms: Turbulent velocity in :math:`\mbox{m s}^{-1}`.
    :type vrms: float
    :returns: Gas temperature in K.
    :rtype: float
    """
    
    dv = sigma
    if fwhm:
        dv = fwhm2sigma(dv)
        
    return (np.power(dv, 2.) - np.power(vrms, 2.))*m/8314.46262103


def doppler_temp_err(sigma, sigma_err, m, vrms, vrms_err, fwhm=False):
    """
    """
    
    dv = sigma
    dv_err = sigma_err
    if fwhm:
        dv = fwhm2sigma(dv)
        dv_err = fwhm2sigma(dv_err)

    cte = m/8314.46262103
    fac1 = 2.*dv*dv_err
    fac2 = 2.*vrms*vrms_err
    
    return np.sqrt((np.power(fac1, 2.) + np.power(fac2, 2.)))*cte


def dv2df(f0, dv):
    """
    Convert a velocity delta to a frequency delta given a central frequency.
    
    :param f0: Rest frequency.
    :type f0: float
    :param dv: Velocity delta in m/s.
    :type dv: float
    :returns: For the given velocity delta the equivalent frequency delta.
    :rtype: float
    """
    
    return dv*f0/c.to('m/s').value


def dv_minus_doppler(dV, ddV, dD, ddD):
    """
    Returns the Lorentzian contribution to the line width assuming that the line has a Voigt profile.
    
    :param dV: Total line width
    :type dV: float
    :param ddV: Uncertainty in the total line width.
    :type ddV: float
    :param dD: Doppler contribution to the line width.
    :type dD: float
    :param ddD: Uncertainty in the Doppler contribution to the line width.
    :returns: The Lorentz contribution to the total line width.
    :rtype: float
    """
    
    a = 0.5346
    b = 0.2166
    
    d = np.power(2.*a*dV, 2) - 4.*(b - a*a)*(np.power(dD, 2.) - np.power(dV, 2.))
    
    if d < 0:
        print("No real solutions, check input.")
        return 0
    
    dL_p = (-2.*a*dV + np.sqrt(d))/(2.*(b - a*a))
    dL_m = (-2.*a*dV - np.sqrt(d))/(2.*(b - a*a))
    
    if dL_m < dV:
        dL = dL_m
        ddL1 = (-2.*a - ((a*a*dV) + 8.*(b - a*a)*dV)/np.sqrt(np.power(2.*a*dV, 2.) - 4.*(b-a*a)*(np.power(dD, 2.) - np.power(dV, 2.))))/(2.*(b - a*a))
    else:
        dL = dL_p
        ddL1 = (-2.*a + ((a*a*dV) + 8.*(b - a*a)*dV)/np.sqrt(np.power(2.*a*dV, 2.) - 4.*(b-a*a)*(np.power(dD, 2.) - np.power(dV, 2.))))/(2.*(b - a*a))
        
    ddL2 = 4.*(b - a*a)*dD/np.sqrt(np.power(2.*a*dV, 2.) - 4.*(b - a*a)*(np.power(dD, 2.) - np.power(dV, 2.)))
    
    ddL = np.sqrt(np.power(ddL1*ddV, 2) + np.power(ddL2*ddV, 2)) 
    
    return dL, ddL


def dv_minus_doppler2(dV, ddV, dD, ddD):
    """
    Returns the Lorentzian contribution to the line width assuming that the line has a Voigt profile.
    
    :param dV: Total line width
    :type dV: float
    :param ddV: Uncertainty in the total line width.
    :type ddV: float
    :param dD: Doppler contribution to the line width.
    :type dD: float
    :param ddD: Uncertainty in the Doppler contribution to the line width.
    :returns: The Lorentz contribution to the total line width.
    :rtype: float
    """
    
    a = 0.5346
    b = 0.2166
    
    den = (a*a - b)
    dif = np.power(dV, 2.) - np.power(dD, 2.)
    d = np.power(a*dV, 2) - den*dif
    
    if d < 0:
        print("No real solutions, check input.")
        return 0
    
    dL_p = (a*dV + np.sqrt(d))/den
    dL_m = (a*dV - np.sqrt(d))/den
    
    if dL_m < dV:
        dL = dL_m
        ddL1 = (a + (a*a*dV - dV*den)/np.sqrt(np.power(a*dV, 2) - den*dif))/den
    else:
        dL = dL_p
        ddL1 = (a - (a*a*dV - dV*den)/np.sqrt(np.power(a*dV, 2) - den*dif))/den
        
    ddL2 = dD/np.sqrt(np.power(a*dV, 2) - den*dif)
    
    ddL = np.sqrt(np.power(ddL1*ddV, 2) + np.power(ddL2*ddV, 2)) 
    
    return dL, ddL


def f2n(f, line, n_max=1500):
    """
    Converts a given frequency to a principal quantum number :math:`n` for a given line.
    
    :param f: Frequency to convert. (MHz)
    :type f: array
    :param line: The equivalent :math:`n` will be referenced to this line.
    :type line: string
    :param n_max: Maximum n number to include in the search. (optional, Default 1)
    :type n_max: int
    :returns: Corresponding :math:`n` for a given frequency and line. \
    If the frequency is not an exact match, then it will return an empty array.
    :rtype: array
    """
    
    line, nn, freq = make_line_list(line, n_max=n_max)
    fii = np.in1d(freq, f)
    
    return nn[fii]


def find_lines_sb(freq, line, z=0, verbose=False):
    """
    Finds if there are any lines of a given type in the frequency range.
    The line frequencies are corrected for redshift.
    
    :param freq: Frequency axis in which to search for lines (MHz). It should not contain \
    NaN or inf values.
    :type freq: array
    :param line: Line type to search for.
    :type line: string
    :param z: Redshift to apply to the rest frequencies.
    :type z: float
    :param verbose: Verbose output?
    :type verbose: bool
    :returns: Lists with the princpipal quantum number and the reference \
    frequency of the line. The frequencies are redshift corrected in MHz.
    :rtype: array.
    
    See Also
    --------
    load_ref : Describes the format of line and the available ones.
    
    Examples
    --------
    >>> from crrlpy import crrls
    >>> freq = [10, 11]
    >>> ns, rf = crrls.find_lines_sb(freq, 'RRL_CIalpha')
    >>> ns
    array([843., 844., 845., 846., 847., 848., 849., 850., 851., 852., 853.,
           854., 855., 856., 857., 858., 859., 860., 861., 862., 863., 864.,
           865., 866., 867., 868., 869.])
    """
    
    # Load the reference frequencies.
    qn, restfreq = load_ref(line)
    
    # Correct rest frequencies for redshift.
    reffreq = restfreq/(1.0 + z)
    
    if verbose:
        print("Subband edges: {0}--{1}".format(freq[0], freq[-1]))
    
    # Check which lines lie within the sub band.
    mask_ref = (freq[0] < reffreq) & (freq[-1] >= reffreq)
    reffreqs = reffreq[mask_ref]
    refqns = qn[mask_ref]
    
    nlin = len(reffreqs)
    if verbose:
        print("Found {0} {1} lines within the subband.".format(nlin, line))
        if nlin > 1:
            print("Corresponding to n values: {0}--{1}".format(refqns[0], refqns[-1]))
        elif nlin == 1:
            print("Corresponding to n value {0} and frequency {1} MHz".format(refqns[0], reffreqs[0]))

    return refqns, reffreqs


def freq2vel(f0, f):
    """
    Convert a frequency axis to a velocity axis given a central frequency.
    Uses the radio definition of velocity.
    
    :param f0: Rest frequency for the conversion. (Hz)
    :type f0: float
    :param f: Frequencies to be converted to velocity. (Hz)
    :type f: numpy array
    :returns: f converted to velocity given a rest frequency :math:`f_{0}`.
    :rtype: numpy array
    """
    
    return c.to('m/s').value*(1. - f/f0)


def fwhm2sigma(fwhm):
    """
    Converts a FWHM to the standard deviation, :math:`\\sigma` of a Gaussian distribution.
    
    .. math:
       
       FWHM=2\\sqrt{2\\ln2}\\sigma
       
    :param fwhm: FWHM of the Gaussian.
    :type fwhm: array
    :returns: Equivalent standard deviation of a Gausian with a Full Width at Half Maximum `fwhm`.
    :rtype: array
    
    :Example:
    
    >>> 1/fwhm2sigma(1)
    2.3548200450309493
    """
    
    return fwhm/(2.*np.sqrt(2.*np.log(2.)))


def gauss_area(amplitude, sigma):
    """
    Returns the area under a Gaussian of a given amplitude and sigma.
    
    .. math:
    
        Area=\\sqrt(2\\pi)A\\sigma
        
    :param amplitude: Amplitude of the Gaussian, :math:`A`.
    :type A: array
    :param sigma: Standard deviation fo the Gaussian, :math:`\\sigma`.
    :type sigma: array
    :returns: The area under a Gaussian of a given amplitude and standard deviation.
    :rtype: array
    """
    
    return amplitude*sigma*np.sqrt(2.*np.pi)


def gauss_area_err(amplitude, amplitude_err, sigma, sigma_err):
    """
    Returns the error on the area of a Gaussian of a given `amplitude` and `sigma` \
    with their corresponding errors. It assumes no correlation between `amplitude` and 
    `sigma`.
    
    :param amplitude: Amplitude of the Gaussian.
    :type amplitude: array
    :param amplitude_err: Error on the amplitude.
    :type amplitude_err: array
    :param sigma: Standard deviation of the Gaussian.
    :param sigma_err: Error on sigma.
    :returns: The error on the area.
    :rtype: array
    """
    
    err1 = np.power(amplitude_err*sigma*np.sqrt(2*np.pi), 2)
    err2 = np.power(sigma_err*amplitude*np.sqrt(2*np.pi), 2)
    
    return np.sqrt(err1 + err2)


def gauss_area2peak(area, sigma):
    """
    Returns the maximum value of a Gaussian function given its
    amplitude and standard deviation "math:`\\sigma`.
    
    """
    
    return area/sigma/np.sqrt(2.*np.pi)


def gauss_area2peak_err(amplitude, area, darea, sigma, dsigma):
    """
    Returns the maximum value of a Gaussian function given its
    amplitude, area and standard deviation "math:`\\sigma`.
    
    """
    
    err1 = amplitude/area*darea
    err2 = amplitude/sigma*dsigma
    
    return np.sqrt(np.power(err1, 2.) + np.power(err2, 2.))


def gaussian(x, sigma, center, amplitude):
    """
    Gaussian function in one dimension.
    
    :param x: x values for which to evaluate the Gaussian.
    :type x: array
    :param sigma: Standard deviation of the Gaussian.
    :type sigma: float
    :param center: Center of the Gaussian.
    :type center: float
    :param amplitude: Peak value of the Gaussian.
    :type amplitude: float
    :returns: Gaussian function of the given amplitude and standard deviation evaluated at x.
    :rtype: array
    """
    
    #return amplitude/(sigma*np.sqrt(2.*np.pi))*np.exp(-np.power((x - center), 2.)/(2.*np.power(sigma, 2.)))
    return amplitude*np.exp(-np.power((x - center), 2.)/(2.*np.power(sigma, 2.)))


def get_axis(header, axis):
    """
    Constructs a cube axis.
    
    :param header: Fits cube header.
    :type header: pyfits header
    :param axis: Axis to reconstruct.
    :type axis: int
    :returns: cube axis
    :rtype: numpy array
    """
    
    axis = str(axis)
    dx = header.get("CDELT" + axis)
    try:
        dx = float(dx)
        p0 = header.get("CRPIX" + axis)
        x0 = header.get("CRVAL" + axis)
        
    except TypeError:
        dx = 1
        p0 = 1
        x0 = 1

    n = header.get("NAXIS" + axis)
    
    p0 -= 1 # Fits files index start at 1, not for python.
    
    axis = np.arange(x0 - p0*dx, x0 - p0*dx + n*dx, dx)
    
    if len(axis) > n:
        axis = axis[:-1]
    
    return axis


def get_rchi2(x_obs, x_mod, y_obs, y_mod, dy_obs, dof):
    """
    Computes the reduced :math:`\\chi` squared, :math:`\\chi_{\\nu}^{2}=\\chi^{2}/dof`.
    
    :param x_obs: Abscissa values of the observations.
    :type x_obs: array
    :param x_mod: Abscissa values of the model.
    :type x_mod: array
    :param y_obs: Ordinate values of the observations.
    :type y_obs: array
    :param y_mod: Ordinate values of the model.
    :type y_mod: array
    :param dy_obs: Error on the ordinate values of the observations.
    :type dy_obs: array
    :param dof: Degrees of freedom.
    :type dof: float
    """
        
    # Find the equivalent model points
    n_indx_mod = []
    for i,n in enumerate(x_obs):
        n_indx_mod.append(np.where(x_mod == n)[0][0])
        
    return np.sum(np.power(y_obs - y_mod[n_indx_mod], 2.)/np.power(dy_obs, 2))/(len(x_obs) - dof)


def get_line_mask(freq, reffreq, v0, dv):
    """
    Return a mask with ranges where a line is expected in the given frequency range for \
    a line with a given reference frequency at expected velocity v0 and line width dv0.
    
    :param freq: Frequency axis where the line is located.
    :type freq: numpy array or list
    :param reffreq: Reference frequency for the line.
    :type reffreq: float
    :param v0: Velocity of the line.
    :type v0: float, km/s
    :param dv: Velocity range to mask.
    :type dv: float, km/s
    :returns: Mask centered at the line center and width `dv0` referenced to the input `freq`.
    """
    
    f0 = vel2freq(reffreq, v0*1e3)
    df0 = dv2df(reffreq*1e6, dv0*1e3)
    
    df = abs(freq[0] - freq[1])
    
    f0_indx = utils.best_match_indx(f0, freq, df/2.0)
    
    mindx0 = f0_indx - df0/df/1e6
    mindxf = f0_indx + df0/df/1e6
    
    return [mindx0, mindxf]


def get_line_mask2(freq, reffreq, dv):
    """
    Return a mask with ranges where a line is expected in the given frequency range for \
    a line with a given reference frequency and line width dv.
    
    :param freq: Frequency axis where the line is located.
    :type freq: numpy array or list
    :param reffreq: Reference frequency for the line.
    :type reffreq: float
    :param dv: Velocity range to mask.
    :type dv: float, km/s
    :returns: Mask centered at the line center and width `dv0` referenced to the input `freq`.
    """
    
    df = dv2df(reffreq, dv*1e3)
    df_chan = utils.get_min_sep(freq)
    f0_indx = utils.best_match_indx(reffreq, np.asarray(freq))

    f_mini = int(f0_indx - df/df_chan)
    if f_mini < 0:
        f_mini = 0
    f_maxi = int(f0_indx + df/df_chan)

    return [f_mini, f_maxi]


def get_rms(data, axis=None):
    """
    Computes the rms of the given data.
    
    :param data: Array with values where to compute the rms.
    :type data: numpy array or list
    :param axis: Axis over which to compute the rms. Default: None
    :type axis: int
    :returns: The rms of data.
    
    .. math::
    
        \\mbox{rms}=\\sqrt{\\langle\\mbox{data}\\rangle^{2}+V[\\mbox{data}]}
        
    where :math:`V` is the variance of the data.
    """
    
    rms = np.sqrt(np.power(data.std(axis=axis), 2.) +
                  np.power(data.mean(axis=axis), 2.))

    return rms


def is_number(str):
    """
    Checks wether a string is a number or not.
    
    :param str: String.
    :type str: string
    :returns: True if `str` can be converted to a float.
    :rtype: bool
    
    :Example:
    
    >>> is_number('10')
    True
    """
    
    try:
        float(str)
        return True
    except ValueError:
        return False


def lambda2vel(wav0, wav):
    """
    Convert a wavelength axis to a velocity axis given a rest wavelength.
    Uses the optical definition of velocity.
    
    :param wav0: Rest frequency for the conversion.)
    :type wav0: float
    :param wav: Frequencies to be converted to velocity.
    :type wav: numpy array
    :returns: Velocity. (Default: m/s)
    :rtype: numpy array
    """
    
    return c*(wav/wav0 - 1.)


def levelpopc(t):
    """
    Fraction of carbon atoms in the 3/2 state relative to the 1/2 state.
    
    :param t: Kinetic temperature.
    :type t: float
    """

    g12 = 2.
    g32 = 4.

    return g32/g12*np.exp(-92./t)


def linear(x, a, b):
    """
    Linear model.
    
    :param x: x values where to evalueate the line.
    :type x: array
    :param a: Slope of the line.
    :type a: float
    :param b: y value for x equals 0.
    :type b: float
    :returns: A line defined by :math:`ax+b`.
    :rtype: array
    """
    
    return a*x + b


def load_model(prop, specie, temp, dens, other=None):
    """
    Loads a model for the CRRL emission.
    """
    
    LOCALDIR = os.path.dirname(os.path.realpath(__file__))
    ldir = "{0}/{1}/{2}".format(LOCALDIR, 'models', 'radtrans')
    if specie == 'alpha':
        if other:
            if 'width' in prop:
                mod_file = '{0}/Diffuse_CMB_bn_velturb_{1}_{2}_{3}_linewidth.dat'.format(ldir, temp, dens, other)
            else:
                mod_file = '{0}/Diffuse_CMB_bn_velturb_{1}_{2}_{3}_line.dat'.format(ldir, temp, dens, other)
        else:
            if 'width' in prop:
                mod_file = '{0}/Diffuse_CMB_bn_velturb_{1}_{2}_linewidth.dat'.format(ldir, temp, dens)
            else:
                mod_file = '{0}/Diffuse_CMB_bn_velturb_{1}_{2}_line.dat'.format(ldir, temp, dens)
    else:
        if other:
            if 'width' in prop:
                mod_file = '{0}/Diffuse_CMB_bn_velturb_{4}_{1}_{2}_{3}_linewidth.dat'.format(ldir, temp, dens, other, specie)
            else:
                mod_file = '{0}/Diffuse_CMB_bn_velturb_{4}_{1}_{2}_{3}_line.dat'.format(ldir, temp, dens, other, specie)
        else:
            if 'width' in prop:
                mod_file = '{0}/Diffuse_CMB_bn_velturb_{4}_{1}_{2}_linewidth.dat'.format(ldir, temp, dens, specie)
            else:
                mod_file = '{0}/Diffuse_CMB_bn_velturb_{4}_{1}_{2}_line.dat'.format(ldir, temp, dens, specie)
    
    model = np.loadtxt(mod_file)
    
    if 'width' in prop:
        
        qni = model[:,0]
        qnf = model[:,1]
        freq = model[:,2]
        dD = model[:,3]
        dLc = model[:,4]
        dLr = model[:,5]
        I = model[:,6]
        
        return np.array([qni, qnf, freq, dD, dLc, dLr, I])
    
    else:
        
        qn = model[:,0]
        freq = model[:,1]
        Ic = model[:,2]
        tau = model[:,3]
        eta_nu = model[:,4]
        
        return np.array([qn, freq, Ic, tau, eta_nu])


def load_ref(line):
    """
    Loads the reference spectrum for the specified line.
    
    | Available lines:
    | RRL_CIalpha
    | RRL_CIbeta
    | RRL_CIdelta
    | RRL_CIgamma
    | RRL_CI13alpha
    | RRL_HeIalpha
    | RRL_HeIbeta
    | RRL_HIalpha
    | RRL_HIbeta
    | RRL_SIalpha
    | RRL_SIbeta
    
    More lines can be added by including a list in the 
    linelist directory.
    
    Parameters
    ----------
    line : string
           Line for which the principal quantum number and reference frequencies are desired.
    
    Returns
    -------
    n : array
            Principal quantum numbers. 
    reference_frequencies : array
                            Reference frequencies of the lines inside the spectrum in MHz.
    """
    
    LOCALDIR = os.path.dirname(os.path.realpath(__file__))
    refspec = np.loadtxt('{0}/linelist/{1}.txt'.format(LOCALDIR, line),
                         usecols=(2,3))
    qn = refspec[:,0]
    reffreq = refspec[:,1]
    
    return qn, reffreq


def lookup_freq(n, line):
    """
    Returns the frequency of a line given the transition number n.
    
    :param n: Principal quantum number to look up for.
    :type n: int
    :param line: Line for which the frequency is desired.
    :type line: string
    :returns: Frequency of line(n).
    :rtype: float
    """
    
    qns, freqs = load_ref(line)
    indx = utils.best_match_indx(n, qns)
    
    return freqs[indx]


def lorentz_width(n, ne, Te, Tr, W, dn=1):
    """
    Gives the Lorentzian line width due to a combination of radiation and \
    collisional broadening. The width is the FWHM in Hz. \
    It uses the models of Salgado et al. (2015).
    
    :param n: Principal quantum number for which to evaluate the Lorentz widths.
    :type n: array
    :param ne: Electron density to use in the collisional broadening term.
    :type ne: float
    :param Te: Electron temperature to use in the collisional broadening term.
    :type Te: float
    :param Tr: Radiation field temperature.
    :type Tr: float
    :param W: Cloud covering factor used in the radiation broadening term.
    :type W: float
    :param dn: Separation between the levels of the transition. e.g., `dn=1` for CIalpha.
    :type dn: int
    :returns: The Lorentz width of a line due to radiation and collisional broadening.
    :rtype: array
    """
    
    dL_r = radiation_broad_salgado(n, W, Tr)
    dL_p = pressure_broad_salgado(n, Te, ne, dn)
    
    return dL_r + dL_p


def mask_outliers(data, m=2):
    """
    Masks values larger than m times the data median. \
    This is similar to sigma clipping.
    
    :param data: Data to mask.
    :type data: array
    :returns: An array of the same shape as data with True where the data \
    should be flagged.
    :rtype: array
    
    :Example:
    
    >>> data = [1,2,3,4,5,6]
    >>> mask_outliers(data, m=1)
    array([ True, False, False, False, False,  True])
    """
    
    return abs(data - np.median(data)) > m*np.std(data)


def n2f(n, line, n_min=1, n_max=1500, unitless=True):
    """
    Converts a given principal quantum number n to the 
    frequency of a given line.
    """
    
    line, nn, freq, trans = make_line_list(line, n_min, n_max, unitless)
    nii = np.in1d(nn, n)
    
    return freq[nii]


def natural_sort(list):
    """ 
    Sort the given list in the way that humans expect. \
    Sorting is done in place.
    
    :param list: List to sort.
    :type list: list
    
    :Example:
    
    >>> my_list = ['spec_3', 'spec_4', 'spec_1']
    >>> natural_sort(my_list)
    >>> my_list
    ['spec_1', 'spec_3', 'spec_4']
    """
    
    list.sort(key=alphanum_key)
    
    
def ngaussian(x, sigma, center):
    """
    Normalized Gaussian distribution.
    """
    
    return 1./(np.sqrt(2.*np.pi)*sigma)*np.exp(-0.5*np.power((x - center)/sigma, 2.))


def pressure_broad(n, te, ne):
    """
    Pressure induced broadening in Hz.
    Shaver (1975) Eq. (64a) for te <= 1000 K and
    Eq. (61) for te > 1000 K.
    """
    
    if te <= 1000:
        dnup = 2e-5*np.power(te, -3./2.)*np.exp(-26./np.power(te, 1./3.))*ne*np.power(n, 5.2)
    else:
        dnup = 3.74e-8*ne*np.power(n, 4.4)*np.power(te, -0.1)
        
    return dnup


def pressure_broad_salgado(n, te, ne, dn=1):
    """
    Pressure induced broadening in Hz.
    This gives the FWHM of a Lorentzian line.
    Salgado et al. (2017)
    
    :param n: Principal quantum number for which to compute the line broadening.
    :type n: float or array
    :param Te: Electron temperature to use when computing the collisional line width.
    :type Te: float
    :param ne: Electron density to use when computing the collisional line width.
    :type ne: float
    :param dn: Difference between the upper and lower level for which the line width is computed. (default 1)
    :type dn: int
    :returns: The collisional broadening FWHM in Hz using Salgado et al. (2015) formulas.
    :rtype: float or array
    """
    
    a, g = pressure_broad_coefs(te)
    
    return ne*np.power(10., a)*(np.power(n, g) + np.power(n + dn, g))/2./np.pi


def pressure_broad_coefs(Te):
    """
    Defines the values of the constants :math:`a` and :math:`\\gamma` that go into the collisional broadening formula
    of Salgado et al. (2017).
    
    :param Te: Electron temperature.
    :type Te: float
    :returns: The values of :math:`a` and :math:`\\gamma`.
    :rtype: list
    """
    
    te = [10, 20, 30, 40, 50, 60, 70, 80, 90,
          100, 200, 300, 400, 500, 600, 700,
          800, 900, 1000, 2000, 3000, 4000, 5000,
          6000, 7000, 8000, 9000, 10000, 20000, 30000]
    
    te_indx = utils.best_match_indx(Te, te)
    
    a = [-10.974098,           
         -10.669695,
         -10.494541,
         -10.370271,
         -10.273172,
         -10.191374,
         -10.124309,
         -10.064037,
         -10.010153,
         -9.9613006,
         -9.6200366,
         -9.4001678,
         -9.2336349,
         -9.0848840,
         -8.9690170,
         -8.8686695,
         -8.7802238,
         -8.7012421,
         -8.6299908,
         -8.2718376,
         -8.0093937,
         -7.8344941,
         -7.7083367,
         -7.6126791,
         -7.5375720,
         -7.4770500,
         -7.4272885,
         -7.3857095,
         -7.1811733,
         -7.1132522]
    
    gammac = [5.4821631,
              5.4354009,
              5.4071360,
              5.3861013,
              5.3689105,
              5.3535398,
              5.3409679,
              5.3290318,
              5.3180304,
              5.3077770,
              5.2283700,
              5.1700702,
              5.1224893,
              5.0770049,
              5.0408369,
              5.0086342,
              4.9796105,
              4.9532071,
              4.9290080,
              4.8063682,
              4.7057576,
              4.6356118,
              4.5831746,
              4.5421547,
              4.5090104,
              4.4815675,
              4.4584053,
              4.4385507,
              4.3290786,
              4.2814240]
    
    a_func = interpolate.interp1d(te, a,
                                  kind='linear',
                                  bounds_error=True,
                                  fill_value=0.0)
    
    g_func = interpolate.interp1d(te, gammac,
                                  kind='linear',
                                  bounds_error=True,
                                  fill_value=0.0)
    
    return [a_func(Te), g_func(Te)]


def radiation_broad(n, W, tr):
    """
    Radiation induced broadening in Hz.
    Shaver (1975)
    """
    
    return 8e-17*W*tr*np.power(n, 5.8)


def radiation_broad_salgado(n, w, tr):
    """
    Radiation induced broadening in Hz.
    This gives the FWHM of a Lorentzian line.
    Salgado et al. (2017)
    """
    
    return 6.096e-17*w*tr*np.power(n, 5.8)


def radiation_broad_salgado_general(n, w, tr, nu0, alpha):
    """
    Radiation induced broadening in Hz.
    This gives the FWHM of a Lorentzian line.
    The expression is valid for power law like radiation fields.
    Salgado et al. (2017)
    """
    
    cte = 2./np.pi*2.14e4*np.power(6.578e15/nu0, alpha + 1.)*k_B.cgs.value*nu0
    dnexp = alpha - 2.
    
    return w*cte*tr*np.power(n, -3.*alpha - 2.)*(1. + np.power(2., dnexp) + np.power(3., dnexp))


def rval(te, ne, nh, rates='TH1985'):
    """
    """
    
    if rates == 'TH1985':
        gammah = 5.8e-10*te**2e-2 # cm3 s-1
        gammae = 4.51e-6/te**0.5 # cm3 s-1
    elif rates == 'PG2012':
        gammah = 4e-11*(16. + 3.5e-1*te**5e-1 + 48./te) # cm3 s-1
        gammae = 8.7e-8*(te/2e3)**(-3.7e-1) # cm3 s-1        
    
    fac1 = ne*gammae
    fac2 = nh*gammah
    # Level population of the fine structure line
    # N32*Ar+N32*ne*gammae+N32*nh*gammah = N12*ne* gammae+N12*nh*gammah
    # 2.4e-6 is the spontaneous emission coefficient for the C+ line
    
    return (fac1 + fac2)/(fac1 + fac2 + 2.4e-6)


def sigma2fwhm(sigma):
    """
    Converts the :math:`\\sigma` parameter of a Gaussian distribution to its FWHM.
    
    :param sigma: :math:`\\sigma` value of the Gaussian distribution.
    :type sigma: float
    :returns: The FWHM of a Gaussian with a standard deviation :math:`\\sigma`.
    :rtype: float
    """
    
    return sigma*2.*np.sqrt(2.*np.log(2.))


def sigma2fwhm_err(dsigma):
    """
    Converts the error on the sigma parameter of a Gaussian distribution \
    to the error on the FWHM.
    
    :param dsigma: Error on sigma of the Gaussian distribution.
    :type sigma: float
    :returns: The error on the FWHM of a Gaussian with a standard deviation :math:`\\sigma`.
    :rtype: float
    """
    
    return dsigma*2.*np.sqrt(2.*np.log(2.))


def sigma2fwtm(sigma):
    """
    Converts the :math:`\\sigma` parameter of a Gaussian distribution to its FWTM.
    
    :math:`\mbox{FWTM}=2(2\log(10))^{1/2}\\sigma`
    
    :param sigma: Standard deviation of the Gaussian distribution.
    :type sigma: float
    :returns: Full width at a tenth of the maximum.
    :rtype: float
    """
    
    return sigma*2.*np.sqrt(2.*np.log(10.))


def signal2noise(snr0, fwhm, dx, prop='amplitude'):
    """
    Signal to noise ratio of the corresponding line property, Lenz & Ayres (1992).
    
    :param snr0: Signal-to-noise ratio computed as peak/rms.
    :type snr0: float
    :param fwhm: FWHM of the line.
    :type fwhm: float
    :param dx: Channel spacing.
    :type dx: float
    :param prop: Line property. Can be one of 'amplitude', 'center', 'FWHM' or 'area'.
    :type prop: str
    :returns: Signal-to-noise ratio assuming a Gaussian line profile.
    :rtype: float
    """
    
    cx = {'amplitude':0.7,
          'center':1.47,
          'FWHM':0.61,
          'area':0.7}
    
    return cx[prop]*np.sqrt(fwhm/dx)*snr0


def tryint(str):
    """
    Returns an integer if `str` can be represented as one.
    
    :param str: String to check.
    :type str: string
    :returns: int(str) if str can be cast to an int, else str.
    :rtype: int or str
    """
    
    try:
        return int(str)
    except:
        return str
    

def vel2freq(f0, vel):
    """
    Convert a velocity axis to a frequency axis given a central frequency.
    Uses the radio definition, :math:`\\nu=f_{0}(1-v/c)`.
    
    :param f0: Rest frequency in Hz.
    :type f0: float
    :param vel: Velocity to convert in m/s.
    :type vel: float or array
    :returns: The frequency which is equivalent to vel.
    :rtype: float or array
    """
    
    return f0*(1. - vel/c.to('m/s').value)


def voigt_(x, y):
    # The Voigt function is also the real part of 
    # w(z) = exp(-z^2) erfc(iz), the complex probability function,
    # which is also known as the Faddeeva function. Scipy has 
    # implemented this function under the name wofz()

    z = x + 1j*y
    I = wofz(z).real

    return I


def voigt(x, sigma, gamma, center, amplitude):
    """
    The Voigt line shape in terms of its physical parameters.
    
    :param x: independent variable
    :param sigma: HWHM of the Gaussian
    :param gamma: HWHM of the Lorentzian
    :param center: the line center
    :param amplitude: the line area
    """

    ln2 = np.log(2)
    f = np.sqrt(ln2)
    rx = (x - center)/sigma * f
    ry = gamma/sigma * f

    V = amplitude*f/(sigma*np.sqrt(np.pi)) * voigt_(rx, ry)

    return V


def voigt_area(amp, fwhm, gamma, sigma):
    """
    Returns the area under a Voigt profile. \
    This approximation has an error of less than 0.5%
    """
    
    l = 0.5*gamma
    g = np.sqrt(2*np.log(2))*sigma
    k = g/(g+l)
    c = 1.572 + 0.05288*k + -1.323*k**2 + 0.7658*k**3
    
    return c*amp*fwhm

def voigt_area2(peak, fwhm, gamma, sigma):
    """
    Area under the Voigt profile using the expression provided by Sorochenko & Smirnov (1990).
    
    Parameters
    ----------
    peak : :obj:`float`
          Peak of the Voigt line profile.
    fwhm : :obj:`float`
          Full width at half maximum of the Voigt profile.
    gamma : :obj:`float`
          Full width at half maximum of the Lorentzian profile.
    sigma : :obj:`float`
          Full width at half maximum of the Doppler profile.
    """
    
    p = 1.57 - 0.507*np.exp(-0.85*gamma/sigma)
    
    return peak*fwhm*p

def voigt_area_err(area, amp, damp, fwhm, dfwhm, gamma, sigma):
    """
    Returns the error of the area under a Voigt profile. \
    Assumes that the parameter c has an error of 0.5%.
    """
    
    l = 0.5*gamma
    g = np.sqrt(2*np.log(2))*sigma
    k = g/(g+l)
    c = 1.572 + 0.05288*k + -1.323*k**2 + 0.7658*k**3
    
    err_a = area/amp*damp
    err_f = area/fwhm*dfwhm
    err_c = area/c*0.5/100.0
    
    err = np.sqrt(err_a**2 + err_f**2 + err_c**2)
    
    return err

def voigt_fwhm(dD, dL):
    """
    Computes the FWHM of a Voigt profile. \
    http://en.wikipedia.org/wiki/Voigt_profile#The_width_of_the_Voigt_profile
    
    .. math::
    
        FWHM_{\\rm{V}}=0.5346dL+\\sqrt{0.2166dL^{2}+dD^{2}}
    
    :param dD: FWHM of the Gaussian core.
    :type dD: array
    :param dL: FWHM of the Lorentz wings.
    :type dL: array
    :returns: The FWHM of a Voigt profile.
    :rtype: array
    """
    
    return np.multiply(0.5346, dL) + np.sqrt(np.multiply(0.2166, np.power(dL, 2)) + np.power(dD, 2))


def voigt_fwhm_err(dD, dL, ddD, ddL):
    """
    Computes the error in the FWHM of a Voigt profile. \
    http://en.wikipedia.org/wiki/Voigt_profile#The_width_of_the_Voigt_profile
    
    :param dD: FWHM of the Gaussian core.
    :type dD: array
    :param dL: FWHM of the Lorentz wings.
    :type dL: array
    :param ddD: Error on the FWHM of the Gaussian.
    :type ddD: array
    :param ddL: Error on the FWHM of the Lorentzian.
    :type ddL: array
    :returns: The FWHM of a Voigt profile.
    :rtype: array
    """
    
    f = 0.02/100.
    a = 0.5346
    b = 0.2166
    
    dT1 = np.power(a + np.multiply(np.multiply(b, dL)/np.sqrt(b*np.power(dL, 2) + np.power(dD, 2)), ddL), 2)
    dT2 = np.power(np.multiply(dD, ddD)/np.sqrt(b*np.power(dL, 2) + np.power(dD, 2)), 2)
    dT = np.sqrt(dT1 + dT2)
    
    dT = np.sqrt(np.power(dT, 2) + np.power(f*voigt_fwhm(dD, dL), 2))
    
    return dT


def voigt_peak(A, alphaD, alphaL):
    """
    Gives the peak of a Voigt profile given its Area and the \
    Half Width at Half Maximum of the Gaussian and Lorentz profiles.
    
    :param A: Area of the Voigt profile.
    :type A: array
    :param alphaD: HWHM of the Gaussian core.
    :type alphaD: array
    :param alphaL: HWHM of the Lorentz wings.
    :type alphaL: array
    :returns: The peak of the Voigt profile.
    :rtype: array
    """
    
    y = alphaL/alphaD*np.sqrt(np.log(2.))
    z = 0. + 1j*y
    K = wofz(z).real
    
    peak = A/alphaD*np.sqrt(np.log(2.)/np.pi)*K
    
    return peak


def voigt_peak2area(peak, alphaD, alphaL):
    """
    Converts the peak of a Voigt profile into the area under the profile \
    given the Half Width at Half Maximum of the profile components.
    
    :param peak: Peak of the Voigt profile.
    :type peak: array
    :param alphaD: HWHM of the Gaussian core.
    :type alphaD: array
    :param alphaL: HWHM of the Lorentz wings.
    :type alphaL: array
    :returns: The area under the Voigt profile.
    :rtype: array
    """
    
    y = alphaL/alphaD*np.sqrt(np.log(2))
    z = 0 + 1j*y
    K = wofz(z).real
    
    A = peak*alphaD/(np.sqrt(np.log(2)/np.pi)*K)
    
    return A
    

def voigt_peak_err(peak, A, dA, alphaD, dalphaD):
    """
    Gives the error on the peak of the Voigt profile. \
    It assumes no correlation between the parameters and that they are \
    normally distributed.
    
    :param peak: Peak of the Voigt profile.
    :type peak: array
    :param A: Area under the Voigt profile.
    :param dA: Error on the area `A`.
    :type dA: array
    :param alphaD: HWHM of the Gaussian core.
    :type alphaD: array
    """
    
    dpeak = abs(peak)*np.sqrt(np.power(dalphaD/alphaD, 2.) + np.power(dA/A, 2.))
    
    return dpeak

if __name__ == "__main__":
    import doctest
    doctest.testmod()
