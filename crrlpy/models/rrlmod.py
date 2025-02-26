#!/usr/bin/env python

"""
.. module:: rrlmod
   :platform: Unix
   :synopsis: RRL model tools.

.. moduleauthor:: Pedro Salas <psalas@strw.leidenuniv.nl>

"""

#__docformat__ = 'reStructuredText'

from __future__ import division

import os
import glob
import re
import pickle
import numpy as np

from scipy.constants import physical_constants as pc

import astropy.units as u
import astropy.constants as ac

from astropy.constants import h, k_B, c, m_e, Ryd, e
from astropy.modeling.blackbody import blackbody_nu

from crrlpy import frec_calc as fc
from crrlpy.crrls import natural_sort, f2n, n2f, load_ref
from crrlpy.utils import best_match_indx


LOCALDIR = os.path.dirname(os.path.realpath(__file__))


def beta(n, bn, te, line='RRL_CIalpha'):
    """
    Computes the correction factor for stimulated emission.
    
    :param n: principal quantum number.
    :param bn: level population departure coefficient.
    :param te: electron temperature.
    """
    
    qns, freq = load_ref(line) # qns lists the final quantum numbers, nu->nl=qns.
    nmin_idx = np.argmin(abs(qns - n.min()))
    nmax_idx = np.argmin(abs(qns - n.max()))
    freq = freq[nmin_idx:nmax_idx]*1e6 # Hz

    h_ = pc['Planck constant'][0]*1e7
    kboltzmann_ = pc['Boltzmann constant'][0]*1e7
    hnukt = h_*freq/kboltzmann_/te
    beta = (1. - bn[1:]/bn[:-1]*np.exp(-hnukt))/(1. - np.exp(-hnukt))

    return beta


def bnbeta_approx(n, Te, ne, Tr):
    """
    Approximates :math:`b_{n}\\beta_{n^{\\prime}n}` 
    for a particular set of conditions.
    Uses Equation (B1) of Salas et al. (2016).
    
    :param n: Principal quantum number
    :type n: int
    :param Te: Electron temperature in K.
    :type Te: float
    :param ne: Electron density per cubic centimeters.
    :type ne: float
    :param Tr: Temperature of the radiation field in K at 100 MHz.
    :type Tr: float
    :returns: The value of :math:`b_{n}\\beta_{n^{\\prime}n}` given an approximate expression.
    :rtype: float
    """
    
    bnbeta0 = load_betabn('5d1', 0.05, 
                          other='case_diffuse_2d3')
    bnbeta0 = bnbeta0[np.where(bnbeta0[:,0] == n), -1]
    
    bnbeta = bnbeta0*(Te/50.)*np.power(ne/0.05, 0.5)*np.power(Tr/2000., -0.1)
    
    return bnbeta


def bnbeta_approx_full(Te, ne, Tr, coefs):
    """
    Approximates :math:`b_{n}\\beta_{n^{\\prime}n}` given a set of coefficients.
    Uses Equations (5) and (B1)-(B5) of Salas et al. (2016).
    """
    
    a0 = coefs[0] + coefs[1]*Tr + coefs[2]*np.power(Tr, 2.)
    a1 = coefs[3] + coefs[4]*Tr
    b0 = coefs[5] + coefs[6]*Tr + coefs[7]*np.power(Tr, 2.)
    b1 = coefs[8] + coefs[9]*Tr + coefs[10]*np.power(Tr, 2.)
    c0 = coefs[11] + coefs[12]*Tr + coefs[13]*np.power(Tr, 2.)
    c1 = coefs[14] + coefs[15]*Tr + coefs[16]*np.power(Tr, 2.)
    
    bnbeta = (a0 + a1*Te)/np.power((b0 + b1*Te)/ne + 1., c0 + c1*Te)
    
    return bnbeta


def broken_plaw(nu, nu0, T0, alpha1, alpha2):
    """
    Defines a broken power law.
    
    .. math::
    
       T(\\nu) = T_{0}\\left(\\dfrac{\\nu}{\\nu_{0}}\\right)^{\\alpha_1}\\mbox{ if }\\nu<\\nu_{0}
       
       T(\\nu) = T_{0}\\left(\\dfrac{\\nu}{\\nu_{0}}\\right)^{\\alpha_2}\\mbox{ if }\\nu\\geq\\nu_{0}
    
    :param nu: Frequency.
    :param nu0: Frequency at which the power law breaks.
    :param T0: Value of the power law at nu0.
    :param alpha1: Index of the power law for nu<nu0.
    :param alpha2: Index of the power law for nu>=nu0.
    :returns: Broken power law evalueated at nu. 
    """
        
    low = plaw(nu, nu0, T0, alpha1) * (nu < nu0)
    hgh = plaw(nu, nu0, T0, alpha2) * (nu >= nu0)
    
    return low + hgh
    
    
def eta(freq, Te, ne, nion, Z, Tr, trans, n_max=1500):
    """
    Returns the correction factor for the Planck function.
    """
    
    kl = kappa_line_lte(Te, ne, nion, Z, Tr, trans, n_max=1500)
    kc = kappa_cont(freq, Te, ne, nion, Z)
    
    return (kc + kl*bni)/(kc + kl*bnf*bnfni)


def fnnp_app(n, dn):
    """
    Eq. (1) Menzel (1969)
    """
    
    return n*mdn(dn)*(1. + 1.5*dn/n)


def I_Bnu(specie, Z, n, Inu_funct, *args):
    """
    Calculates the product :math:`B_{n+\\Delta n,n}I_{\\nu}` to \
    compute the line broadening due to a radiation field :math:`I_{\\nu}`.
    
    :param specie: Atomic specie to calculate for.
    :type specie: string
    :param n: Principal quantum number at which to evaluate :math:`\\dfrac{2}{\\pi}\\sum\\limits_{\\Delta n}B_{n+\\Delta n,n}I_{n+\\Delta n,n}(\\nu)`.
    :type n: int or list
    :param Inu_funct: Function to call and evaluate :math:`I_{n+\\Delta n,n}(\\nu)`. It's first argument must be the frequency.
    :type Inu_funct: function
    :param args: Arguments to `Inu_funct`. The frequency must be left out. \
    The frequency will be passed internally in units of MHz. Use the same \
    unit when required. `Inu_funct` must take the frequency as first parameter.
    :returns: (Hz)
    :rtype: array
    
    :Example:
    
    >>> I_Bnu('CI', 1.,  500, I_broken_plaw, 800, 26*u.MHz.to('Hz'), -1., -2.6)
    array([6.6554062])
    
    """
    
    cte = 2.*np.pi**2.*e.gauss**2./(h.cgs.value*m_e.cgs.value*c.cgs.value**2.*Ryd.to('1/cm')*Z**2.)

    try:
        Inu = np.empty((len(n), 5))
        BninfInu = np.empty((len(n), 5))
        nu = np.empty((len(n), 5))
    except TypeError:
        Inu = np.empty((1, 5))
        BninfInu = np.empty((1, 5))
        nu = np.empty((1, 5))
    
    for dn in range(1,6):
        nu[:,dn-1] = n2f(n, specie+fc.set_trans(dn))
        Inu[:,dn-1] = Inu_funct(nu[:,dn-1]*1e6, *args).cgs.value
        BninfInu[:,dn-1] = cte.cgs.value*n**6./(dn*(n + dn)**2.)*mdn(dn)*Inu[:,dn-1]
    
    return 2./np.pi*BninfInu.sum(axis=1)


def I_broken_plaw(nu, Tr, nu0, alpha1, alpha2):
    """
    Returns the blackbody function evaluated at nu. 
    As temperature a broken power law is used.
    The power law shape has parameters: Tr, nu0, alpha1 and alpha2.
    
    :param nu: Frequency. (Hz) or astropy.units.Quantity_
    :type nu: (Hz) or astropy.units.Quantity_
    :param Tr: Temperature at nu0. (K) or astropy.units.Quantity_
    :param nu0: Frequency at which the spectral index changes. (Hz) or astropy.units.Quantity_
    :param alpha1: spectral index for :math:`\\nu<\\nu_0`
    :param alpha2: spectral index for :math:`\\nu\\geq\\nu_0`
    :returns: Specific intensity in :math:`\\rm{erg}\\,\\rm{cm}^{-2}\\,\\rm{Hz}^{-1}\\,\\rm{s}^{-1}\\,\\rm{sr}^{-1}`. See `astropy.analytic_functions.blackbody.blackbody_nu`__
    :rtype: astropy.units.Quantity_
    
    .. _astropy.units.Quantity: http://docs.astropy.org/en/stable/api/astropy.units.Quantity.html#astropy.units.Quantity
    __ blackbody_
    .. _blackbody: http://docs.astropy.org/en/stable/api/astropy.analytic_functions.blackbody.blackbody_nu.html#astropy.analytic_functions.blackbody.blackbody_nu
    """
    
    Tbpl = broken_plaw(nu, nu0, Tr, alpha1, alpha2)
    
    bnu_bpl = blackbody_nu(nu, Tbpl)
    
    return bnu_bpl


def I_cont(nu, Te, tau, I0, unitless=False):
    """
    Computes the specific intensity due to a blackbody at temperature :math:`T_{e}` and optical depth :math:`\\tau`. It considers that there is 
    background radiation with :math:`I_{0}`.
    
    :param nu: Frequency.
    :type nu: (Hz) or astropy.units.Quantity_
    :param Te: Temperature of the source function. (K) or astropy.units.Quantity_
    :param tau: Optical depth of the medium.
    :param I0: Specific intensity of the background radiation. Must have units of erg / (cm2 Hz s sr) or see `unitless`.
    :param unitless: If True the return 
    :returns: The specific intensity of a ray of light after traveling in an LTE \
    medium with source function :math:`B_{\\nu}(T_{e})` after crossing an optical \
    depth :math:`\\tau_{\\nu}`. The units are erg / (cm2 Hz s sr). See `astropy.analytic_functions.blackbody.blackbody_nu`__
    
    __ blackbody_
    .. _blackbody: http://docs.astropy.org/en/stable/api/astropy.analytic_functions.blackbody.blackbody_nu.html#astropy.analytic_functions.blackbody.blackbody_nu
    """
    
    bnu = blackbody_nu(nu, Te)
    
    if unitless:
        bnu = bnu.cgs.value
        
    return bnu*(1. - np.exp(-tau)) + I0*np.exp(-tau)


def I_external(nu, Tbkg, Tff, tau_ff, Tr, nu0=100e6*u.MHz, alpha=-2.6):
    """
    This method is equivalent to the IDL routine 
    
    :param nu: Frequency. (Hz) or astropy.units.Quantity_
    
    .. _astropy.units.Quantity: http://docs.astropy.org/en/stable/api/astropy.units.Quantity.html#astropy.units.Quantity
    """
    
    if Tbkg.value != 0:
        bnu_bkg = blackbody_nu(nu, Tbkg)
    else:
        bnu_bkg = 0
    
    if Tff.value != 0:
        bnu_ff = blackbody_nu(nu, Tff)
        exp_ff = (1. - np.exp(-tau_ff))
    else:
        bnu_ff = 0
        exp_ff = 0
        
    if Tr.value != 0:
        Tpl = plaw(nu, nu0, Tr, alpha)#Tr*np.power(nu/nu0, alpha)
        bnu_pl = blackbody_nu(nu, Tpl)
    else:
        bnu_pl = 0
    
    return bnu_bkg + bnu_ff*exp_ff + bnu_pl


def I_total(nu, Te, tau, I0, eta):
    """
    """
    
    bnu = blackbody_nu(nu, Te)
    
    exp = np.exp(-tau)
    
    return bnu*eta*(1. - exp) + I0*exp


def itau(temp, dens, line, n_min=5, n_max=1000, other='', verbose=False, value='itau', location=LOCALDIR):
    """
    Gives the integrated optical depth for a given temperature and density.
    It assumes that the background radiation field dominates the continuum emission.
    The emission measure is unity. The output units are Hz.
    
    :param temp: Electron temperature. Must be a string of the form '8d1'.
    :type temp: string
    :param dens: Electron density.
    :type dens: float
    :param line: Line to load models for.
    :type line: string
    :param n_min: Minimum n value to include in the output. Default 1
    :type n_min: int
    :param n_max: Maximum n value to include in the output. Default 1500, Maximum allowed value 9900
    :type n_max: int
    :param other: String to search for different radiation fields and others.
    :type other: string
    :param verbose: Verbose output?
    :type verbose: bool
    :param value: ['itau'|'bbnMdn'|'None'] Value to output. itau will output the integrated optical depth. \
    bbnMdn will output the :math:`\\beta_{n,n^{\\prime}}b_{n}` times the oscillator strenght :math:`M(\\Delta n)`. \
    None will output the :math:`\\beta_{n,n^{\\prime}}b_{n}` values.
    :type value: string
    :returns: The principal quantum number and its asociated value.
    """

    t = str2val(temp)
    d = float(dens)
    
    dn = fc.set_dn(line)
    mdn_ = mdn(dn)
    
    bbn = load_betabn(temp, dens, other, line, verbose, location=location)
    nimin = best_match_indx(n_min, bbn[:,0])
    nimax = best_match_indx(n_max, bbn[:,0])
    n = bbn[nimin:nimax,0]
    b = bbn[nimin:nimax,1]
    
    if value == 'itau':
        i = itau_norad(n, t, b, dn, mdn_)
    elif value == 'bbnMdn':
        i = b*dn*mdn_
    else:
        i = b
        
    return n, i


def itau_h(temp, dens, trans, n_max=1000, other='', verbose=False, value='itau'):
    """
    Gives the integrated optical depth for a given temperature and density. 
    The emission measure is unity. The output units are Hz.
    """

    t = str2val(temp)
    d = dens
    
    dn = fc.set_dn(trans)
    mdn_ = mdn(dn)
    
    bbn = load_betabn_h(temp, dens, other, trans, verbose)
    n = bbn[:,0]
    b = bbn[:,1]

    b = b[:n_max]
    n = n[:n_max]
    
    if value == 'itau':
        #i = -1.069e7*dn*mdn*b*np.exp(1.58e5/(np.power(n, 2)*t))/np.power(t, 5./2.)
        i = itau_norad(n, t, b, dn, mdn_)
    elif value == 'bbnMdn':
        i = b*dn*mdn_
    else:
        i = b
        
    return n, i
  
  
def itau_norad(n, Te, b, dn, mdn_):
    """
    Returns the optical depth using the approximate solution to the 
    radiative transfer problem.
    """
    
    return -1.069e7*dn*mdn_*b*np.exp(1.58e5/(np.power(n, 2.)*Te))/np.power(Te, 5./2.)


def itau_lte(n, Te, dn, mdn_, em):
    """
    Returns the CRRL optical depth integrated in velocity in units of Hz.
    """
    
    return 1.069e7*dn*mdn_*np.exp(1.58e5/(np.power(n, 2.)*Te))/np.power(Te, 5./2.)*em


def j_line_lte(n, ne, nion, Te, Z, trans):
    """
    """
    
    trans = fc.set_name(trans)
    
    Aninf = np.loadtxt('{0}/rates/einstein_Anm_{1}.txt'.format(LOCALDIR, trans))
    cte = h/4./np.pi
    Nni = level_pop_lte(n, ne, nion, Te, Z)
    lc = line_center(nu)
    
    return cte*Aninf[:,2]*Nni*lc


def kappa_cont(freq, Te, ne, nion, Z):
    """
    Computes the absorption coefficient for the free-free process.
    """
    
    nu = freq.to('GHz').value
    v = 0.65290+2./3.*np.log10(nu) - np.log10(Te.to('K').value)
    
    kc = np.zeros(len(nu))
    
    #mask_1 = v <= -2.6
    mask_2 = (v > -5) & (v <= -0.25)
    mask_3 = v > -0.25
    
    #kc[mask_1] = 6.9391e-8*np.power(Z, 2)*ne*nion*np.power(nu[mask_1], -2.)* \
                 #np.power(1e4/Te.to('K').value, 1.5)* \
                 #(4.6950 - np.log10(Z) + 1.5*np.log(Te.to('K').value/1e4) - np.log10(nu[mask_1]))
    
    v_2 = v[mask_2]
    log10I_m0 = -1.232644*v_2 + 0.098747
    kc[mask_2] = kappa_cont_base(nu[mask_2], Te.to('K').value, ne.cgs.value, 
                                 nion.cgs.value, Z)*np.power(10., log10I_m0)
    
    v_3 = v[mask_3]
    log10I_m0 = -1.084191*v_3 + 0.135860
    kc[mask_3] = kappa_cont_base(nu[mask_3], Te.to('K').value, ne.cgs.value, 
                                 nion.cgs.value, Z)*np.power(10., log10I_m0)
    
    #if v < -2.:
        #kc = 6.9391e-8*np.power(Z, 2)*ne*nion*np.power(nu, -2.)*np.power(1e4/Te, 1.5)* \
             #(4.6950 - np.log10(Z) + 1.5*np.log(Te/1e4) - np.log10(nu))
    #elif v >= -2. and v <= -0.25:
        #log10I_m0 = -1.232644*v + 0.098747
    #elif v > -0.25:
        #log10I_m0 = -1.084191*v + 0.135860
    
    #if v >= -2.:
        #kc = 4.6460/np.power(nu, 7./3.)/np.power(Te, 1.5)* \
            #(np.exp(4.7993e-2*nu/Te) - 1.)* \
            #np.exp(aliv/np.log10(np.exp(1)))#*np.exp(-h*freq/k_B/Te)
        
    return kc*u.pc**-1*np.exp(-h.cgs.value*nu/k_B.cgs.value/Te.cgs.value)


def kappa_cont_base(nu, Te, ne, nion, Z):
    """
    
    """
    
    return 4.6460/np.power(nu, 7./3.)/np.power(Te, 1.5)* \
            (np.exp(4.7993e-2*nu/Te) - 1.)*np.power(Z, 8./3.)*ne*nion


def kappa_line(Te, ne, nion, Z, Tr, trans, n_max=1500):
    """
    Computes the line absorption coefficient for CRRLs between levels :math:`n_{i}` and :math:`n_{f}`, :math:`n_{i}>n_{f}`.
    This can only go up to :math:`n_{\\rm{max}}` 1500 because of the tables used for the Einstein Anm coefficients.
    
    :param Te: Electron temperature of the gas. (K)
    :type Te: float
    :param ne: Electron density. (:math:`\\mbox{cm}^{-3}`)
    :type ne: float
    :param nion: Ion density. (:math:`\\mbox{cm}^{-3}`)
    :type nion: float
    :param Z: Electric charge of the atoms being considered.
    :type Z: int
    :param Tr: Temperature of the radiation field felt by the gas. This specifies the temperature of the field at 100 MHz. (K)
    :type Tr: float
    :param trans: Transition for which to compute the absorption coefficient.
    :type trans: string
    :param n_max: Maximum principal quantum number to include in the output.
    :type n_max: int<1500
    :returns: 
    :rtype: array
    """
    
    cte = np.power(c, 2.)/(16.*np.pi)*np.power(np.power(h, 2)/(2.*np.pi*m_e*k_B), 3./2.)
    
    bn = load_bn(val2str(Te), ne, other='case_diffuse_{0}'.format(val2str(Tr)))
    bn = bn[:np.where(bn[:,0] == n_max)[0]]
    Anfni = np.loadtxt('{0}/rates/einstein_Anm_{1}.txt'.format(LOCALDIR, trans))
    
    # Cut the Einstein Amn coefficients table to match the bn values
    i_bn_i = best_match_indx(bn[0,0], Anfni[:,1])
    i_bn_f = best_match_indx(bn[-1,0], Anfni[:,0])
    Anfni = Anfni[i_bn_i:i_bn_f+1]
    
    ni = Anfni[:,0]
    nf = Anfni[:,1]
    
    omega_ni = 2*np.power(ni, 2)
    omega_i = 1.
    
    xi_ni = xi(ni, Te, Z)
    xi_nf = xi(nf, Te, Z)
    
    exp_ni = np.exp(xi_ni.value)
    exp_nf = np.exp(xi_nf.value)
    
    #print len(Anfni), len(bn[1:,-1]), len(bn[:-1,-1]), len(omega_ni[:]), len(ni), len(exp_ni), len(exp_nf)
    kl = cte.value/np.power(Te, 3./2.)*ne*nion*Anfni[:,2]*omega_ni[:]/omega_i*(bn[1:,-1]*exp_ni - bn[:-1,-1]*exp_nf)
    
    return kl


def kappa_line_lte(nu, Te, ne, nion, Z, Tr, line, n_min=1, n_max=1500):
    """
    Returns the line absorption coefficient under LTE conditions.
    
    :param nu: Frequency. (Hz)
    :type nu: array
    :param Te: Electron temperature of the gas. (K)
    :type Te: float
    :param ne: Electron density. (:math:`\\mbox{cm}^{-3}`)
    :type ne: float
    :param nion: Ion density. (:math:`\\mbox{cm}^{-3}`)
    :type nion: float
    :param Z: Electric charge of the atoms being considered.
    :type Z: int
    :param Tr: Temperature of the radiation field felt by the gas. This specifies the temperature of the field at 100 MHz. (K)
    :type Tr: float
    :param trans: Transition for which to compute the absorption coefficient.
    :type trans: string
    :param n_max: Maximum principal quantum number to include in the output.
    :type n_max: int<1500
    :returns: 
    :rtype: array
    """
    
    ni = f2n(nu.to('MHz').value, line, n_max) + 1.
    
    trans = fc.set_name(line)
    
    cte = (np.power(c, 2.)/(8.*np.pi))
    Aninf = np.loadtxt('{0}/rates/einstein_Anm_{1}.txt'.format(LOCALDIR, trans))
    Aninf = Aninf[np.where(Aninf[:,1] == n_min)[0]:np.where(Aninf[:,1] == n_max)[0]]
    
    exp = np.exp(-h*nu/k_B/Te)
    Nni = level_pop_lte(ni, ne, nion, Te, Z)
    
    return cte/np.power(nu, 2.)*Nni*Aninf[:,2]*(1. - exp)#*np.power(Aninf[:,0]/Aninf[:,1], 2.)
    

def level_pop_lte(n, ne, nion, Te, Z):
    """
    Returns the level population of level n.
    The return has units of :math:`\\mbox{cm}^{-3}`.
    """
    
    omega_ni = 2.*np.power(n, 2.)
    omega_i = 1.
    
    xi_n = xi(n, Te, Z)
    
    exp_xi_n = np.exp(xi_n.value)
    
    Nn = ne*nion*np.power(np.power(h, 2.)/(2.*np.pi*m_e*k_B*Te), 1.5)*omega_ni/omega_i/2.*exp_xi_n
    
    return Nn


def load_bn(te, ne, tr='', ncrit='1.5d3', n_min=5, n_max=1000, verbose=False, location=LOCALDIR):
    """
    Loads the bn values from the CRRL models.
    
    :param te: Electron temperature of the model.
    :type te: string
    :param ne: Electron density of the model.
    :type ne: string
    :param other: Radiation field of the model or any other string with model characteristics.
    :type other: string
    :param verbose: Verbose output?
    :type verbose: bool
    :returns: The :math:`b_{n}` value for the given model conditions.
    :rtype: array
    """
    
    #LOCALDIR = os.path.dirname(os.path.realpath(__file__))
    
    if tr == '-' or tr == '' or tr == 0:
        model_file = 'Carbon_opt_T_{0}_ne_{1}_ncrit_{2}_vriens_delta_500_vrinc_nmax_9900_dat'.format(te, ne, ncrit)
        if verbose:
            print("Loading {0}".format(model_file))
    else:
        model_file = 'Carbon_opt_T_{0}_ne_{1}_ncrit_{2}_{3}_vriens_delta_500_vrinc_nmax_9900_dat'.format(te, ne, ncrit, tr)
        if verbose:
            print("Loading {0}".format(model_file))
    model_path = glob.glob('{0}/{1}'.format(location, model_file))[0]
    if verbose:
        print("Loaded {0}".format(model_path))
    bn = np.loadtxt(model_path)
    
    nimin = best_match_indx(n_min, bn[:,0])
    nimax = best_match_indx(n_max, bn[:,0])
    bn = bn[nimin:nimax+1]
    
    return bn


def load_bn_h(te, ne, other='', n_min=5, n_max=1000, verbose=False):
    """
    Loads the bn values from the HRRL models.
    
    :param te: Electron temperature of the model.
    :type te: string
    :param ne: Electron density of the model.
    :type ne: string
    :param other: Radiation field of the model or any other string with model characteristics.
    :type other: string
    :param verbose: Verbose output?
    :type verbose: bool
    :returns: The :math:`b_{n}` value for the given model conditions.
    :rtype: array
    """
    
    #LOCALDIR = os.path.dirname(os.path.realpath(__file__))
    
    if other == '-' or other == '':
        mod_file = 'H_bn2/Hydrogen_opt_T_{1}_ne_{2}_ncrit_8d2_vriens_delta_500_vrinc_nmax_9900_dat'.format(LOCALDIR, te, ne)
        if verbose:
            print("Loading {0}".format(mod_file))
        mod_file = glob.glob('{0}/H_bn2/Hydrogen_opt_T_{1}_ne_{2}*_ncrit_8d2_vriens_delta_500_vrinc_nmax_9900_dat'.format(LOCALDIR, te, ne))[0]
    else:
        mod_file = 'H_bn2/Hydrogen_opt_T_{1}_ne_{2}_ncrit_8d2_{3}_vriens_delta_500_vrinc_nmax_9900_dat'.format(LOCALDIR, te, ne, other)
        if verbose:
            print("Loading {0}".format(mod_file))
        mod_file = glob.glob('{0}/H_bn2/Hydrogen_opt_T_{1}_ne_{2}*_ncrit_8d2_{3}_vriens_delta_500_vrinc_nmax_9900_dat'.format(LOCALDIR, te, ne, other))[0]
    
    if verbose:
        print("Loaded {0}".format(mod_file))
    bn = np.loadtxt(mod_file)
    
    nimin = best_match_indx(n_min, bn[:,0])
    nimax = best_match_indx(n_max, bn[:,0])
    bn = bn[nimin:nimax+1]
    
    return bn


def load_bn_all(n_min=5, n_max=1000, verbose=False, location=LOCALDIR):
    """
    """
    
    models = glob.glob('{0}/bn2/*_dat'.format(location))
    natural_sort(models)
    models = np.asarray(models)
    
    models_tr = sorted(models, key=lambda x: (str2val(x.split('_')[3]), 
                                              float(x.split('_')[5]),
                                              str2val(x.split('_')[10]) if len(x.split('_')) > 17 else 0))
    models = models_tr
    
    Te = np.zeros(len(models))
    ne = np.zeros(len(models))
    Tr = np.zeros(len(models), dtype='|S20')
    data = np.zeros((len(models), 5, n_max-n_min))
    
    for i,model in enumerate(models):
        if verbose:
            print(model)
        st = model.split('_')[3]
        Te[i] = str2val(st)
        sn = model.split('_')[5].rstrip('0')
        ne[i] = float(sn)
        if len(model.split('_')) <= 17:
            Tr[i] = '-'
        else:
            Tr[i] = '_'.join(model.split('_')[8:11])
        if verbose:
            print("Trying to load model: ne={0}, te={1}, tr={2}".format(ne[i], Te[i], Tr[i]))
        bn = load_bn(st, sn, Tr=Tr[i], n_min=n_min, n_max=n_max, verbose=verbose)
        data[i,0] = bn[:,0]
        data[i,1] = bn[:,1]
        data[i,2] = bn[:,2]
        data[i,3] = bn[:,3]
        data[i,4] = bn[:,4]
        
    return [Te, ne, Tr, data]
  
def load_bn_dict(dict, n_min=5, n_max=1000, verbose=False, location=LOCALDIR, ncrit='1.5d3'):
    """
    Loads the :math:`b_{n}` values defined by dict.
    
    :param dict: Dictionary containing a list with values for Te, ne and Tr.
    :type dict: dict
    :param line: Which models should be loaded.
    :type line: string
    :param n_min: Minimum n number to include in the output.
    :type n_min: int
    :param n_max: Maximum n number to include in the output.
    :type n_max: int
    :param verbose: Verbose output?
    :type verbose: bool
    :returns: List with the :math:`b_{n}` values for the conditions defined by dict.
    :rtype: numpy.array
    
    :Example:
    
    >>> from crrlpy.models import rrlmod
    
    First define the range of parameters
    
    >>> Te = np.array(['1d1', '2d1', '3d1', '4d1', '5d1'])
    >>> ne = np.arange(0.01,0.105,0.01)
    >>> Tr = np.array([800])
    
    Put them in a dictionary
    
    >>> models = {'Te':[t_ for t_ in Te for n_ in ne for tr_ in Tr], \
                  'ne':[round(n_,3) for t_ in Te for n_ in ne for tr_ in Tr], \
                  'Tr':['case_diffuse_{0}'.format(rrlmod.val2str(tr_)) \
                        for t_ in Te for n_ in ne for tr_ in Tr]}
    
    Load the models
    
    >>> bn = rrlmod.load_bn_dict(models, n_min=200, n_max=500, verbose=False)
                                                       
    """
    
    data = np.zeros((len(dict['Te']), 5, n_max-n_min+1))
    
    for i,t in enumerate(dict['Te']):
        
        if verbose:
            print("Trying to load model: ")
            print("ne={0}, Te={1}, Tr={2}".format(dict['ne'][i], t, dict['Tr'][i]))
        
        bn = load_bn(t, dict['ne'][i], n_min=n_min, n_max=n_max, tr=dict['Tr'][i], 
                     ncrit=ncrit, verbose=verbose, location=location)
        
        data[i,0] = bn[:,0]
        data[i,1] = bn[:,1]
        data[i,2] = bn[:,2]
        data[i,3] = bn[:,3]
        data[i,4] = bn[:,4]
        
    return data


def load_itau_all(line='RRL_CIalpha', n_min=5, n_max=1000, verbose=False, value='itau'):
    """
    Loads all the available models for Carbon.
    
    :param line: Which models should be loaded.
    :type line: string
    :param n_min: Minimum n number to include in the output.
    :type n_min: int
    :param n_max: Maximum n number to include in the output.
    :type n_max: int
    :param verbose: Verbose output?
    :type verbose: bool
    :param value: ['itau'\|'bbnMdn'\|None] Which value should be in the output.
    :type value: string
    """
    
    #LOCALDIR = os.path.dirname(os.path.realpath(__file__))
    
    models = glob.glob('{0}/bbn2_{1}/*'.format(LOCALDIR, line))
    natural_sort(models)
    models = np.asarray(models)
    
    models_len = np.asarray([len(model.split('_')) for model in models])
    models_tr = sorted(models, key=lambda x: (str2val(x.split('_')[4]), 
                                                     float(x.split('_')[6]),
                                                     str2val(x.split('_')[11]) if len(x.split('_')) > 17 else 0))
    models = models_tr
    
    Te = np.zeros(len(models))
    ne = np.zeros(len(models))
    other = np.zeros(len(models), dtype='|S20')
    data = np.zeros((len(models), 2, n_max-n_min))
    
    for i,model in enumerate(models):
        if verbose:
            print(model)
        st = model.split('_')[4]
        Te[i] = str2val(st)
        sn = model.split('_')[6].rstrip('0')
        ne[i] = float(sn)
        if len(model.split('_')) <= 17:
            other[i] = '-'
        else:
            other[i] = '_'.join(model.split('_')[9:12])
        if verbose:
            print("Trying to load model: ne={0}, te={1}, tr={2}".format(ne[i], Te[i], other[i]))
        n, int_tau = itau(st, ne[i], line, n_min=n_min, n_max=n_max, 
                          other=other[i], verbose=verbose, 
                          value=value)
        data[i,0] = n
        data[i,1] = int_tau
        
    return [Te, ne, other, data]


def load_itau_all_hydrogen(trans='alpha', n_max=1000, verbose=False, value='itau'):
    """
    Loads all the available models for Hydrogen.
    """
    
    #LOCALDIR = os.path.dirname(os.path.realpath(__file__))
    
    models = glob.glob('{0}/bbn2_RRL_HI{1}/*'.format(LOCALDIR, trans))
    natural_sort(models)
    models = np.asarray(models)
    
    models = sorted(models, key=lambda x: (str2val(x.split('_')[5]), 
                                           float(x.split('_')[7]),
                                           str2val(x.split('_')[11]) if len(x.split('_')) > 17 else 0))
    
    Te = np.zeros(len(models))
    ne = np.zeros(len(models))
    other = np.zeros(len(models), dtype=object)
    data = np.zeros((len(models), 2, n_max))
    
    for i,model in enumerate(models):
        if verbose:
            print(model)
        st = model.split('_')[5]
        Te[i] = str2val(st)
        sn = model.split('_')[7]
        ne[i] = float(sn)
        if len(model.split('_')) <= 18:
            other[i] = '-'
        else:
            other[i] = '_'.join(model.split('_')[10:13])
        if verbose:
            print("Trying to load model: ne={0}, te={1}, tr={2}".format(ne[i], Te[i], other[i]))
        n, int_tau = itau_h(st, sn, trans, n_max=n_max, other=other[i], verbose=verbose, value=value)
        data[i,0] = n
        data[i,1] = int_tau
        
    return [Te, ne, other, data]


def load_itau_all_match(trans_out='alpha', trans_tin='beta', n_max=1000, verbose=False, value='itau'):
    """
    Loads all trans_out models that can be found in trans_tin. This is useful when analyzing line ratios.
    """
    
    #LOCALDIR = os.path.dirname(os.path.realpath(__file__))
    
    target = [f.split('/')[-1] for f in glob.glob('{0}/bbn2_{1}/*'.format(LOCALDIR, trans_tin))]
    models = ['bbn2_{0}/'.format(trans_out) + f for f in target]
    
    [Te, ne, other, data] = load_models(models, trans_out, n_max, verbose, value)
    
    return [Te, ne, other, data]


def load_itau_all_norad(trans='alpha', n_max=1000):
    """
    Loads all the available models.
    """
    
    #LOCALDIR = os.path.dirname(os.path.realpath(__file__))
    
    models = glob.glob('{0}/bbn/*_dat_bn_beta'.format(LOCALDIR))
    natural_sort(models)
    
    Te = np.zeros(len(models))
    ne = np.zeros(len(models))
    other = np.zeros(len(models), dtype='|S20')
    data = np.zeros((len(models), 2, n_max))
    
    for i,model in enumerate(models):
      
        st = model[model.index('T')+2:model.index('T')+5]
        Te[i] = str2val(st)
        
        sn = model[model.index('ne')+3:model.index('ne')+7].split('_')[0]
        ne[i] = str2val(sn)
        
        other[i] = model.split('bn_beta')[-1]

        n, int_tau = itau(st, sn, trans, n_max=1000, other=other[i])

        data[i,0] = n
        data[i,1] = int_tau
        
    return [Te, ne, other, data]


def load_itau_dict(dict, line, n_min=5, n_max=1000, verbose=False, value='itau', location=LOCALDIR):
    """
    Loads the models defined by dict.
    
    :param dict: Dictionary containing a list with values for Te, ne and Tr.
    :type dict: dict
    :param line: Which models should be loaded.
    :type line: string
    :param n_min: Minimum n number to include in the output.
    :type n_min: int
    :param n_max: Maximum n number to include in the output.
    :type n_max: int
    :param verbose: Verbose output?
    :type verbose: bool
    :param value: ['itau'\|'bbnMdn'\|None] Which value should be in the output.
    :type value: string
    
    :Example:
    
    >>> from crrlpy.models import rrlmod
    
    First define the range of parameters
    
    >>> Te = np.array(['1d1', '2d1', '3d1', '4d1', '5d1'])
    >>> ne = np.arange(0.01,0.105,0.01)
    >>> Tr = np.array([2000])
    
    Put them in a dictionary
    
    >>> models = {'Te':[t_ for t_ in Te for n_ in ne for tr_ in Tr],
    ...           'ne':[round(n_,3) for t_ in Te for n_ in ne for tr_ in Tr],
    ...           'Tr':['case_diffuse_{0}'.format(rrlmod.val2str(tr_))
    ...                 for t_ in Te for n_ in ne for tr_ in Tr]}
    
    # Load the models
    
    >>> itau_mod = rrlmod.load_itau_dict(models, 'CIalpha', n_min=250, n_max=300, \
                                         verbose=False, value='itau')
                                                       
    
    """
    
    data = np.zeros((len(dict['Te']), 2, n_max-n_min))
    
    for i,t in enumerate(dict['Te']):
        
        if verbose:
            print("Trying to load model: ne={0}, Te={1}, Tr={2}".format(dict['ne'][i], 
                                                                        t, 
                                                                        dict['Tr'][i]))
        n, int_tau = itau(t, dict['ne'][i], line, n_min=n_min, n_max=n_max, 
                          other=dict['Tr'][i], verbose=verbose, value=value, location=location)
        
        data[i,0] = n
        data[i,1] = int_tau
        
    return data


def load_itau_nelim(temp, dens, trad, trans, n_max=1000, verbose=False, value='itau'):
    """
    Loads models given a temperature, radiation field and an 
    upper limit for the electron density.
    """
    
    #LOCALDIR = os.path.dirname(os.path.realpath(__file__))
    
    models = glob.glob('{0}/bbn2_{1}/*_T_{2}_*_{3}_*'.format(LOCALDIR, trans, 
                                                             temp, trad))
    #print models
    natural_sort(models)
    models = np.asarray(models)
    
    models_len = np.asarray([len(model.split('_')) for model in models])
    models = sorted(models, key=lambda x: (str2val(x.split('_')[4]), 
                                           float(x.split('_')[6]),
                                           str2val(x.split('_')[11]) if len(x.split('_')) > 17 else 0))
    
    models = np.asarray(models)
    nes = np.asarray([float(model.split('_')[6].rstrip('0')) for model in models])
    
    # Only select those models with a density equal or lower than the specified value: dens.
    models = models[nes <= dens]
    #print models
    
    return load_models(models, trans, n_max=n_max, verbose=verbose, value=value)


def load_itau_numpy(filename):
    """
    Loads all the models contained in filename.npy
    
    Parameters
    ----------
    filename : :obj:`string`
              Filename with the models.
    Returns
    -------
    
    """
    
    itau_mod = np.load('{0}.npy'.format(filename))
    head = pickle.load(open('{0}.p'.format(filename), 'rb'))
    
    return head, itau_mod


def load_betabn(temp, dens, other='', trans='RRL_CIalpha', verbose=False, location=LOCALDIR):
    """
    Loads a model for the CRRL emission.
    
    location = "{0}/bbn2_CIalpha".format(rrlmod.LOCALDIR)
    """
    
    #LOCALDIR = os.path.dirname(os.path.realpath(__file__))
    #print LOCALDIR
    
    if trans[:5] == 'RRL_C':
        atom = 'Carbon'
        ncrit = '1.5d3'
    elif trans[:5] == 'RRL_H':
        atom = 'Hydrogen'
        ncrit = '8d2'
    
    if other == '-' or other == '':
        model_file = '{0}_opt_T_{1}_ne_{2}_ncrit_{3}_vriens_delta_500_vrinc_nmax_9900_datbn_beta'.format(atom, temp, dens, ncrit)
        if verbose:
            print('Will try to locate: {0}'.format(model_file))
            print('In: {0}'.format(location))
        model_path = glob.glob('{0}/{1}'.format(location, model_file))[0]
    else:
        model_file = '{0}_opt_T_{1}_ne_{2}_ncrit_{3}_{4}_vriens_delta_500_vrinc_nmax_9900_datbn_beta'.format(atom, temp, dens, ncrit, other)
        if verbose:
            print('Will try to locate: {0}'.format(model_file))
            print('In: {0}'.format(location))
        model_path = glob.glob('{0}/{1}'.format(location, model_file))[0]
    
    if verbose:
        print("Loading {0}".format(model_path))
    data = np.loadtxt(model_path)
    
    return data


def load_betabn_h(temp, dens, other='', trans='alpha', verbose=False):
    """
    Loads a model for the HRRL emission.
    """
    
    #LOCALDIR = os.path.dirname(os.path.realpath(__file__))
    
    if other == '-' or other == '':
        model_file = 'bbn2_RRL_HI{0}/Hydrogen_opt_T_{1}_ne_{2}_ncrit_8d2_vriens_delta_500_vrinc_nmax_9900_datbn_beta'.format(trans, temp, dens)
        if verbose:
            print('Will try to locate: {0}'.format(model_file))
        model_path = glob.glob('{0}/{1}'.format(LOCALDIR, model_file))[0]
    else:
        model_file = 'bbn2_RRL_HI{0}/Hydrogen_opt_T_{1}_ne_{2}_ncrit_8d2_{3}_vriens_delta_500_vrinc_nmax_9900_datbn_beta'.format(trans, temp, dens, other)
        if verbose:
            print('Will try to locate: {0}'.format(model_file))
        model_path = glob.glob('{0}/{1}'.format(LOCALDIR, model_file))[0]
    
    if verbose:
        print("Loading {0}".format(model_path))
    data = np.loadtxt(model_path)
    
    return data


def load_models(models, trans, n_max=1000, verbose=False, value='itau'):
    """
    Loads the models in backwards compatible mode.
    It will sort the models by Te, ne and Tr.
    """

    models = np.asarray(models)
    models = sorted(models, key=lambda x: (str2val(x.split('_')[4]), 
                                           float(x.split('_')[6]),
                                           str2val(x.split('_')[11]) if len(x.split('_')) > 17 else 0))
        
    Te = np.zeros(len(models))
    ne = np.zeros(len(models))
    other = np.zeros(len(models), dtype='|S20')
    data = np.zeros((len(models), 2, n_max))
    
    for i,model in enumerate(models):
        if verbose:
            print(model)
        st = model.split('_')[4]
        Te[i] = str2val(st)
        sn = model.split('_')[6].rstrip('0')
        ne[i] = float(sn)
        if len(model.split('_')) <= 17:
            other[i] = '-'
        else:
            other[i] = '_'.join(model.split('_')[9:12])
        if verbose:
            print("Trying to load model: ne={0}, te={1}, tr={2}".format(ne[i], Te[i], other[i]))
        n, int_tau = itau(st, sn, trans, n_max=n_max, other=other[i], verbose=verbose, value=value)
        data[i,0] = n
        data[i,1] = int_tau
        
    return [Te, ne, other, data]


def make_betabn(line, temp, dens, n_min=5, n_max=1000, other=''):
    """
    """
    
    t = str2val(temp)
    d = str2val(dens)
    
    bn = load_bn(temp, dens, other=other)
    line, n, freq = fc.make_line_list(line, n_min=n_min, n_max=n_max)
    
    # Cut bn first
    bn = bn[np.where(bn[:,0]==n_min)[0]:np.where(bn[:,0]==n_max)[0]]
    freq = freq[np.where(n==bn[0,0])[0]:np.where(n==bn[-1,0])[0]]
    
    beta = np.empty(len(freq))
    
    for i in xrange(len(freq)):
        if i < len(freq)-dn:

            bnn = Decimal(bn[i+dn,-1]) / Decimal(bn[i,-1])
            e = Decimal(-h.value*freq[i]*1e6/(k_B.value*t))
            exp = Decimal(e).exp()
            beta[i] = float((Decimal(1) - bnn*exp)/(Decimal(1) - exp))
        
    return np.array([bn[:-1,0], beta*bn[:-1,1]])


def make_betabn2(line, temp, dens, n_min=5, n_max=1000, other=''):
    """
    """
    
    t = str2val(temp)
    d = dens
    
    dn = fc.set_dn(line)
    bn = load_bn(temp, dens, other=other)
    line, n, freq = fc.make_line_list(line, n_min=n_min, n_max=bn[-1,0]+1)
    
    # Cut bn first
    bn = bn[np.where(bn[:,0]==n_min)[0]:np.where(bn[:,0]==n_max)[0]]
    #bn = bn[n_min:n_max]
    freq = freq[np.where(n==bn[0,0])[0]:np.where(n==bn[-1,0])[0]]
    
    beta = np.empty(len(freq))
    
    for i in xrange(len(freq)):
        if i < len(freq)-dn:
          
            bnn = Decimal(bn[i+dn,-1]) / Decimal(bn[i,-1])
            e = Decimal(-h.value*freq[i]*1e6/(k_B.value*t))
            exp = Decimal(e).exp()
            beta[i] = float((Decimal(1) - bnn*exp)/(Decimal(1) - exp))
        
    return np.array([bn[:-1,0], beta*bn[:-1,1]])
    
    
def mdn(dn):
    """
    Gives the :math:`M(\\Delta n)` factor for a given :math:`\\Delta n`.
    ref. Menzel (1968)
    
    :param dn: :math:`\\Delta n`.
    :returns: :math:`M(\\Delta n)`
    :rtype: float
    
    :Example:
    
    >>> mdn(1)
    0.1908
    >>> mdn(5)
    0.001812
    """
    
    if dn == 1:
        mdn_ = 0.1908
    if dn == 2:
        mdn_ = 0.02633
    if dn == 3:
        mdn_ = 0.008106
    if dn == 4:
        mdn_ = 0.003492
    if dn == 5:
        mdn_ = 0.001812
        
    return mdn_


def models_dict(Te, ne, Tr):
    """
    Creates a dict for loading models given arrays with ne, Te and Tr.
    """
    
    models = {'Te':np.array([t for t in Te for n in ne for tr in Tr]),
              'Te_v':np.array([round(str2val(t)) for t in Te for n in ne for tr in Tr]),
              'ne':np.array([round(n,3) for t in Te for n in ne for tr in Tr]),
              'Tr':np.array(['case_diffuse_{0}'.format(val2str(tr)) \
                             if tr!= 0 else '-' for t in Te for n in ne for tr in Tr]),
              'Tr_v':np.array([tr if tr!= 0 else '-' for t in Te for n in ne for tr in Tr])}
              
    return models


def plaw(x, x0, y0, alpha):
    """
    Returns a power law.
    
    .. math::
    
       y(x)=y_0\\left(\\frac{x}{x_0}\\right)^{\\alpha}
       
    :param x: x values for which to compute the power law.
    :type x: float or array like
    :param x0: x value for which the power law has amplitude `y0`.
    :type x0: float
    :param y0: Amplitude of the power law at `x0`.
    :type y0: float
    :param alpha: Index of the power law.
    :type alpha: float
    :returns: A power law of index `alpha` evaluated at `x`, with amplitude `y0` at `x0`.
    :rtype: float or array
    """
    
    return y0*np.power(x/x0, alpha)


def str2val(str):
    """
    Converts a string representing a number to a float.
    The string must follow the IDL convention for floats.
    
    :param str: String to convert.
    :type str: string
    :returns: The equivalent number.
    :rtype: float
    
    :Example:
    
    >>> str2val('2d2')
    200.0
    """
    
    try:
        aux = list(map(float, str.split('d')))
        val = aux[0]*np.power(10., aux[1])
    except ValueError:
        val = 0
    
    return val


def val2str(val):
    """
    Converts a float to the string format required for loading the CRRL models.
    
    :param val: Value to convert to a string.
    :type val: float
    :returns: The value of val represented as a string in IDL double format.
    :rtype: string
    
    :Example:
    
    >>> val2str(200)
    '2d2'
    """
    
    d = np.floor(np.log10(val))
    u = val/np.power(10., d)
    
    if u.is_integer():
        return "{0:.0f}d{1:.0f}".format(u, d)
    else:
        return "{0}d{1:.0f}".format(u, d)
    
    
def valid_ne(line):
    """
    Checks all the available models and lists the available ne values.
    """
    
    #LOCALDIR = os.path.dirname(os.path.realpath(__file__))
    
    models = glob.glob('{0}/bbn2_{1}/*'.format(LOCALDIR, line))
    natural_sort(models)
    models = np.asarray(models)
    
    models_len = np.asarray([len(model.split('_')) for model in models])
    #models_tr = models[models_len>17]
    #print models_tr[0].split('_')[11], models_tr[0].split('_')[4], models_tr[0].split('_')[6]
    models = sorted(models, key=lambda x: (str2val(x.split('_')[4]), 
                                           float(x.split('_')[6]),
                                           str2val(x.split('_')[11]) if len(x.split('_')) > 17 else 0))
    ne = np.asarray([float(model.split('_')[6].rstrip('0')) for model in models])
    
    return np.unique(ne)


def chi(n, Te, Z):
    """
    Computes the :math:`\\chi_{n}` value as defined by Salgado et al. (2015).
    """
    
    return np.power(Z, 2.)*h*c*Ryd/(k_B*np.power(n, 2)*Te)


def tau_exact(t, ne, Ni, n, fnnp, line='RRL_CIalpha'):
    """
    Uses the column density of ions as input.
    """
    
    cte = (ac.h**3*ac.e.gauss**2.*np.pi/(np.power(2*np.pi*ac.m_e*ac.k_B, 3./2.)*ac.m_e*ac.c)).cgs
    
    nu = n2f(n, line)*1e6*u.Hz
    
    return cte*n**2*fnnp*ne*Ni/np.power(t, 3./2.)*np.exp(1.57e5*u.K/n**2/t)*(1. - np.exp(-ac.h*nu/(ac.k_B*t)))


if __name__ == "__main__":
    import doctest
    doctest.testmod()
