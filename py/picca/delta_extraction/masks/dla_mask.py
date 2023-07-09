"""This module defines the classes DlaMask and Dla used in the
masking of DLAs"""
import logging

from astropy.table import Table
import fitsio
import numpy as np
from numba import njit

from scipy.special import voigt_profile

from picca.delta_extraction.astronomical_objects.forest import Forest
from picca.delta_extraction.errors import MaskError
from picca.delta_extraction.mask import Mask, accepted_options, defaults
from picca.delta_extraction.utils import (
    ABSORBER_IGM, update_accepted_options, update_default_options)

accepted_options = update_accepted_options(accepted_options, [
    "dla mask limit", "los_id name", "mask file", "filename"
])

defaults = update_default_options(
    defaults, {
        "dla mask limit": 0.8,
        "los_id name": "THING_ID",
    })

np.random.seed(0)
NUM_POINTS = 10000
GAUSSIAN_DIST = np.random.normal(size=NUM_POINTS) * np.sqrt(2)


def dla_profile(lambda_, z_abs, nhi):
    """Compute DLA profile

    Arguments
    ---------
    lambda_: array of floats
    Wavelength (in Angs)

    z_abs: float
    Redshift of the absorption

    nhi: float
    DLA column density in log10(cm^-2)
    """
    transmission = np.exp(
        -tau_lya(lambda_, z_abs, nhi)
        -tau_lyb(lambda_, z_abs, nhi))
    return transmission

### Implementation based on Garnett2018
LAMBDA_LYA = float(ABSORBER_IGM["LYA"]) ## Lya wavelength [A]
def tau_lya(lambda_, z_abs, nhi):
    """Compute the optical depth for Lyman-alpha absorption.

    Arguments
    ---------
    lambda_: array of floats
    Wavelength (in Angs)

    z_abs: float
    Redshift of the absorption

    nhi: float
    DLA column density in log10(cm^-2)

    Return
    ------
    tau: array of float
    The optical depth.
    """
    e = 1.6021e-19 #C
    epsilon0 = 8.8541e-12 #C^2.s^2.kg^-1.m^-3
    f = 0.4164
    mp = 1.6726e-27 #kg
    me = 9.109e-31 #kg
    c = 2.9979e8 #m.s^-1
    k = 1.3806e-23 #m^2.kg.s^-2.K-1
    T = 5*1e4 #K
    gamma = 6.2648e+08 #s^-1

    lambda_rest_frame = lambda_/(1+z_abs)
    
    v = c *(lambda_rest_frame/LAMBDA_LYA-1)
    b = np.sqrt(2*k*T/mp)
    small_gamma = gamma*LAMBDA_LYA/(4*np.pi)*1e-10
    
    nhi_m2 = 10**nhi*1e4
    
    tau = nhi_m2*np.pi*e**2*f*LAMBDA_LYA*1e-10
    tau /= 4*np.pi*epsilon0*me*c
    tau *= voigt_profile(v, b/np.sqrt(2), small_gamma)
        
    return tau

LAMBDA_LYB = float(ABSORBER_IGM["LYB"])
def tau_lyb(lambda_, z_abs, nhi):
    """Compute the optical depth for Lyman-beta absorption.

    Arguments
    ---------
    lambda_: array of floats
    Wavelength (in Angs)

    z_abs: float
    Redshift of the absorption

    nhi: float
    DLA column density in log10(cm^-2)

    Return
    ------
    tau: array of float
    The optical depth.
    """
    e = 1.6021e-19 #C
    epsilon0 = 8.8541e-12 #C^2.s^2.kg^-1.m^-3
    f = 0.07912 
    mp = 1.6726e-27 #kg
    me = 9.109e-31 #kg
    c = 2.9979e8 #m.s^-1
    k = 1.3806e-23 #m^2.kg.s^-2.K-1
    T = 5*1e4 #K
    gamma = 4.1641e-01 #s^-1

    lambda_rest_frame = lambda_/(1+z_abs)
    
    v = c *(lambda_rest_frame/LAMBDA_LYB-1)
    b = np.sqrt(2*k*T/mp)
    small_gamma = gamma*LAMBDA_LYB/(4*np.pi)*1e-10
    
    nhi_m2 = 10**nhi*1e4
    
    tau = nhi_m2*np.pi*e**2*f*LAMBDA_LYB*1e-10
    tau /= 4*np.pi*epsilon0*me*c
    tau *= voigt_profile(v, b/np.sqrt(2), small_gamma)
    
    return tau


class DlaMask(Mask):
    """Class to mask DLAs

    Methods
    -------
    __init__
    apply_mask

    Attributes
    ----------
    (see Mask in py/picca/delta_extraction/mask.py)

    dla_mask_limit: float
    Lower limit on the DLA transmission. Transmissions below this number are
    masked

    logger: logging.Logger
    Logger object

    mask: astropy.Table
    Table containing specific intervals of wavelength to be masked for DLAs
    """
    def __init__(self, config):
        """Initializes class instance.

        Arguments
        ---------
        config: configparser.SectionProxy
        Parsed options to initialize class

        Raise
        -----
        MaskError if there are missing variables
        MaskError if input file does not have extension DLACAT
        MaskError if input file does not have fields THING_ID, Z, NHI in extension
        DLACAT
        MaskError upon OsError when reading the mask file
        """
        self.logger = logging.getLogger(__name__)

        super().__init__(config)

        # first load the dla catalogue
        filename = config.get("filename")
        if filename is None:
            raise MaskError("Missing argument 'filename' required by DlaMask")

        los_id_name = config.get("los_id name")
        if los_id_name is None:
            raise MaskError(
                "Missing argument 'los_id name' required by DlaMask")

        self.logger.progress(f"Reading DLA catalog from: {filename}")

        accepted_zcolnames = ["Z_DLA", "Z"]
        z_colname = accepted_zcolnames[0]
        try:
            with fitsio.FITS(filename) as hdul:
                hdul_colnames = set(hdul["DLACAT"].get_colnames())
                z_colname = hdul_colnames.intersection(accepted_zcolnames)
                if not z_colname:
                    raise ValueError(f"Z colname has to be one of {', '.join(accepted_zcolnames)}")
                z_colname = z_colname.pop()
                columns_list = [los_id_name, z_colname, "NHI"]
                cat = {col: hdul["DLACAT"][col][:] for col in columns_list}
        except OSError as error:
            raise MaskError(
                f"Error loading DlaMask. File {filename} does "
                "not have extension 'DLACAT'"
            ) from error
        except ValueError as error:
            aux = "', '".join(columns_list)
            raise MaskError(
                f"Error loading DlaMask. File {filename} does "
                f"not have fields '{aux}' in HDU 'DLACAT'"
            ) from error

        # group DLAs on the same line of sight together
        self.los_ids = {}
        for los_id in np.unique(cat[los_id_name]):
            w = los_id == cat[los_id_name]
            self.los_ids[los_id] = list(zip(cat[z_colname][w], cat['NHI'][w]))
        num_dlas = np.sum([len(los_id) for los_id in self.los_ids.values()])

        self.logger.progress(f'In catalog: {num_dlas} DLAs')
        self.logger.progress(f'In catalog: {len(self.los_ids)} forests have a DLA\n')

        # setup transmission limit
        # transmissions below this number are masked
        self.dla_mask_limit = config.getfloat("dla mask limit")
        if self.dla_mask_limit is None:
            raise MaskError("Missing argument 'dla mask limit' "
                            "required by DlaMask")

        # load mask
        mask_file = config.get("mask file")
        if mask_file is not None:
            try:
                self.mask = Table.read(mask_file,
                                       names=('type', 'wave_min', 'wave_max',
                                              'frame'),
                                       format='ascii')
                self.mask = self.mask['frame'] == 'RF_DLA'
            except (OSError, ValueError) as error:
                raise MaskError(
                    f"ERROR: Error while reading mask_file file {mask_file}"
                ) from error
        else:
            self.mask = Table(names=('type', 'wave_min', 'wave_max', 'frame'))

    def apply_mask(self, forest):
        """Apply the mask. The mask is done by removing the affected
        pixels from the arrays in Forest.mask_fields

        Arguments
        ---------
        forest: Forest
        A Forest instance to which the correction is applied

        Raise
        -----
        MaskError if Forest.wave_solution is not 'log'
        """
        lambda_ = 10**forest.log_lambda

        # load DLAs
        if self.los_ids.get(forest.los_id) is not None:
            dla_transmission = np.ones(len(lambda_))
            for (z_abs, nhi) in self.los_ids.get(forest.los_id):
                dla_transmission *= dla_profile(lambda_, z_abs,
                                                nhi)

            # find out which pixels to mask
            w = dla_transmission > self.dla_mask_limit
            if len(self.mask) > 0:
                for mask_range in self.mask:
                    for (z_abs, nhi) in self.los_ids.get(forest.los_id):
                        w &= ((lambda_ / (1. + z_abs) < mask_range['wave_min'])
                              | (lambda_ /
                                 (1. + z_abs) > mask_range['wave_max']))

            # do the actual masking
            forest.transmission_correction *= dla_transmission
            for param in Forest.mask_fields:
                self._masker(forest, param, w)
