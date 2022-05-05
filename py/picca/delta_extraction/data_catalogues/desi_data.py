"""This module defines the class DesiData to load DESI data
"""
import logging
import numpy as np

from picca.delta_extraction.astronomical_objects.desi_forest import DesiForest
from picca.delta_extraction.astronomical_objects.desi_pk1d_forest import DesiPk1dForest
from picca.delta_extraction.astronomical_objects.forest import Forest
from picca.delta_extraction.data import Data, defaults, accepted_options
from picca.delta_extraction.errors import DataError
from picca.delta_extraction.quasar_catalogues.desi_quasar_catalogue import DesiQuasarCatalogue
from picca.delta_extraction.quasar_catalogues.desi_quasar_catalogue import (
    accepted_options as accepted_options_quasar_catalogue)
from picca.delta_extraction.quasar_catalogues.desi_quasar_catalogue import (
    defaults as defaults_quasar_catalogue)
from picca.delta_extraction.utils import ACCEPTED_BLINDING_STRATEGIES
from picca.delta_extraction.utils_pk1d import spectral_resolution_desi, exp_diff_desi

accepted_options = sorted(
    list(
        set(accepted_options + accepted_options_quasar_catalogue +
            ["blinding", "use non-coadded spectra", "wave solution"])))

defaults = defaults.copy()
defaults.update({
    "delta lambda": 0.8,
    "delta log lambda": 3e-4,
    "blinding": "corr_yshift",
    "use non-coadded spectra": False,
    "wave solution": "lin",
})
defaults.update(defaults_quasar_catalogue)


class DesiData(Data):
    """Abstract class to read DESI data and format it as a list of
    Forest instances.

    Methods
    -------
    (see Data in py/picca/delta_extraction/data.py)
    __init__
    __parse_config
    format_data
    read_data
    set_blinding

    Attributes
    ----------
    (see Data in py/picca/delta_extraction/data.py)

    blinding: str
    A string specifying the chosen blinding strategies. Must be one of the
    accepted values in ACCEPTED_BLINDING_STRATEGIES

    catalogue: astropy.table.Table
    The quasar catalogue

    input_directory: str
    Directory to spectra files.

    logger: logging.Logger
    Logger object

    use_non_coadded_spectra: bool
    If True, load data from non-coadded spectra and coadd them here. Otherwise,
    load coadded data
    """

    def __init__(self, config):
        """Initialize class instance

        Arguments
        ---------
        config: configparser.SectionProxy
        Parsed options to initialize class
        """
        self.logger = logging.getLogger(__name__)

        super().__init__(config)

        # load variables from config
        self.blinding = None
        self.use_non_coadded_spectra = None
        self.__parse_config(config)

        # load z_truth catalogue
        self.catalogue = DesiQuasarCatalogue(config).catalogue

        # read data
        is_mock, is_sv = self.read_data()

        # set blinding
        self.set_blinding(is_mock, is_sv)

    def __parse_config(self, config):
        """Parse the configuration options

        Arguments
        ---------
        config: configparser.SectionProxy
        Parsed options to initialize class

        Raise
        -----
        DataError upon missing required variables
        """
        # instance variables
        self.blinding = config.get("blinding")
        if self.blinding is None:
            raise DataError("Missing argument 'blinding' required by DesiData")
        if self.blinding not in ACCEPTED_BLINDING_STRATEGIES:
            raise DataError(
                "Unrecognized blinding strategy. Accepted strategies "
                f"are {ACCEPTED_BLINDING_STRATEGIES}. "
                f"Found '{self.blinding}'")

        self.use_non_coadded_spectra = config.getboolean(
            "use non-coadded spectra")
        if self.use_non_coadded_spectra is None:
            raise DataError(
                "Missing argument 'use non-coadded spectra' required by DesiData"
            )

    def format_data(self, catalogue, spectrographs_data, targetid_spec,
                    forests_by_targetid, reso_from_truth=False):
        """After data has been read, format it into DesiForest instances

        Instances will be DesiForest or DesiPk1dForest depending on analysis_type

        Arguments
        ---------
        catalogue: astropy.table.Table
        The quasar catalogue fragment associated with this data

        spectrographs_data: dict
        The read data

        targetid_spec: int
        Targetid of the objects to format

        forests_by_targetid: dict
        Dictionary were forests are stored. Its content is modified by this
        function with the new forests.

        reso_from_truth: bool - Default: False
        Specifies whether resolution matrixes are read from truth files (True)
        or directly from data (False)

        Return
        ------
        num_data: int
        The number of instances loaded
        """
        num_data = 0

        # Loop over quasars in catalogue fragment
        for row in catalogue:
            # Find which row in tile contains this quasar
            # It should be there by construction
            targetid = row["TARGETID"]
            w_t = np.where(targetid_spec == targetid)[0]
            if len(w_t) == 0:
                self.logger.warning(
                    f"Error reading {targetid}. Ignoring object")
                continue
            if len(w_t) > 1:
                self.logger.warning(
                    "Warning: more than one spectrum in this file "
                    f"for {targetid}")
            else:
                w_t = w_t[0]
            # Construct DesiForest instance
            # Fluxes from the different spectrographs will be coadded
            for spec in spectrographs_data.values():
                if self.use_non_coadded_spectra:
                    ivar = np.atleast_2d(spec['IVAR'][w_t])
                    ivar_coadded_flux = np.atleast_2d(
                        ivar * spec['FLUX'][w_t]).sum(axis=0)
                    ivar = ivar.sum(axis=0)
                    flux = (ivar_coadded_flux / ivar)
                else:
                    flux = spec['FLUX'][w_t].copy()
                    ivar = spec['IVAR'][w_t].copy()

                args = {
                    "flux": flux,
                    "ivar": ivar,
                    "targetid": targetid,
                    "ra": row['RA'],
                    "dec": row['DEC'],
                    "z": row['Z'],
                }
                args["log_lambda"] = np.log10(spec['WAVELENGTH'])

                if self.analysis_type == "BAO 3D":
                    forest = DesiForest(**args)
                elif self.analysis_type == "PK 1D":
                    if self.use_non_coadded_spectra:
                        exposures_diff = exp_diff_desi(spec, w_t)
                        if exposures_diff is None:
                            continue
                    else:
                        exposures_diff = np.zeros(spec['WAVELENGTH'].shape)
                    if reso_from_truth:
                        reso_sum = spec['RESO'][:, :]
                    else:
                        if len(spec['RESO'][w_t].shape) < 3:
                            reso_sum = spec['RESO'][w_t].copy()
                        else:
                            reso_sum = spec['RESO'][w_t].sum(axis=0)
                    reso_in_pix, reso_in_km_per_s = spectral_resolution_desi(
                        reso_sum, spec['WAVELENGTH'])
                    args["exposures_diff"] = exposures_diff
                    args["reso"] = reso_in_km_per_s
                    args["resolution_matrix"] = reso_sum
                    args["reso_pix"] = reso_in_pix

                    forest = DesiPk1dForest(**args)
                # this should never be entered added here in case at some point
                # we add another analysis type
                else:  # pragma: no cover
                    raise DataError("Unkown analysis type. Expected 'BAO 3D'"
                                    f"or 'PK 1D'. Found '{self.analysis_type}'")

                # rebin arrays
                # this needs to happen after all arrays are initialized by
                # Forest constructor
                forest.rebin()

                # keep the forest
                if targetid in forests_by_targetid:
                    existing_forest = forests_by_targetid[targetid]
                    existing_forest.coadd(forest)
                    forests_by_targetid[targetid] = existing_forest
                else:
                    forests_by_targetid[targetid] = forest

                num_data += 1
        return num_data

    # pylint: disable=no-self-use
    # this method should use self in child classes
    def read_data(self):
        """Read the spectra and formats its data as Forest instances.

        Method to be implemented by child classes.

        Return
        ------
        is_mock: bool
        True if mocks are read, False otherwise

        is_sv: bool
        True if all the read data belong to SV. False otherwise

        Raise
        -----
        DataError if no quasars were found
        """
        raise DataError(
            "Function 'read_data' was not overloaded by child class")

    def set_blinding(self, is_mock, is_sv):
        """Set the blinding in Forest.

        Update the stored value if necessary.

        Attributes
        ----------
        is_mock: boolean
        True if reading mocks, False otherwise

        is_sv: boolean
        True if reading SV data only, False otherwise
        """
        # blinding checks
        if is_mock:
            if self.blinding != "none":  # pragma: no branch
                self.logger.warning(f"Selected blinding, {self.blinding} is "
                                    "being ignored as mocks should not be "
                                    "blinded. 'none' blinding engaged")
                self.blinding = "none"
        elif is_sv:
            if self.blinding != "none":
                self.logger.warning(f"Selected blinding, {self.blinding} is "
                                    "being ignored as SV data should not be "
                                    "blinded. 'none' blinding engaged")
                self.blinding = "none"
        # TODO: remove this when we are ready to unblind
        else:
            if self.blinding != "corr_yshift":
                self.logger.warning(f"Selected blinding, {self.blinding} is "
                                    "being ignored as data should be blinded. "
                                    "'corr_yshift' blinding engaged")
                self.blinding = "corr_yshift"

        # set blinding strategy
        Forest.blinding = self.blinding
