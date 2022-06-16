"""This module defines the abstract class Mask from which all
Masks must inherit
"""
from picca.delta_extraction.errors import MaskError

def _remove_pixels(forest, param, w):
    if param in ['resolution_matrix']:
        setattr(forest, param, getattr(forest, param)[:, w])
    else:
        setattr(forest, param, getattr(forest, param)[w])

def _set_ivar_to_zero(forest, param, w):
    if param == 'ivar':
        forest.ivar[~w] = 0

class Mask:
    """Abstract class from which all Masks must inherit.
    Classes that inherit from this should be initialized using
    a configparser.SectionProxy instance.

    Arguments
    ---------
    keep_masked_pixels: bool (default: False)
    Determines the method to mask pixels. If true, sets ivar to 0.

    Methods
    -------
    __init__
    apply_mask

    Attributes
    ----------
    los_ids: dict
    Empty dictionary to be overloaded by child classes
    
    _masker: function
    If keep_masked_pixels=True, then points to _set_ivar_to_zero.
    Otherwise, points to _remove_pixels.
    """
    def __init__(self, keep_masked_pixels=False):
        """Initialize class instance"""
        self.los_id = {}
        
        if keep_masked_pixels:
            self._masker = _set_ivar_to_zero
        else:
            self._masker = _remove_pixels

    # pylint: disable=no-self-use
    # this method should use self in child classes
    def apply_mask(self, forest):
        """Applies the mask. This function should be
        overloaded with the correct functionallity by any child
        of this class

        Arguments
        ---------
        forest: Forest
        A Forest instance to which the correction is applied

        Raises
        ------
        MaskError if function was not overloaded by child class
        """
        raise MaskError("Function 'apply_mask' was not overloaded by child class")
