from astropy.wcs import WCS
import numpy as np
import xarray as xr
from typing import Union
from .common import _c
from ..._utils.common import _deg_to_rad


def _make_empty_sky_image(
    xds: xr.Dataset,
    phase_center: Union[list, np.ndarray],
    image_size: Union[list, np.ndarray],
    cell_size: Union[list, np.ndarray],
    chan_coords: Union[list, np.ndarray],
    pol_coords: Union[list, np.ndarray],
    time_coords: Union[list, np.ndarray],
    direction_reference: str,
    projection: str,
    spectral_reference: str,
) -> xr.Dataset:
    if len(image_size) != 2:
        raise ValueError("image_size must have exactly two elements")
    if len(phase_center) != 2:
        raise ValueError("phase_center must have exactly two elements")
    if len(cell_size) != 2:
        raise ValueError("cell_size must have exactly two elements")
    wcs_dict = {}
    wcs_dict["NAXIS1"] = image_size[0]
    wcs_dict["CTYPE1"] = f"RA---{projection}"
    wcs_dict["CRVAL1"] = phase_center[0]
    wcs_dict["CRPIX1"] = image_size[0] // 2 + 1
    wcs_dict["CDELT1"] = -abs(cell_size[0])
    wcs_dict["CUNIT1"] = "rad"
    wcs_dict["NAXIS2"] = image_size[1]
    wcs_dict["CTYPE2"] = f"DEC--{projection}"
    wcs_dict["CRVAL2"] = phase_center[1]
    wcs_dict["CRPIX2"] = image_size[1] // 2 + 1
    wcs_dict["CDELT2"] = abs(cell_size[1])
    wcs_dict["CUNIT2"] = "rad"
    w = WCS(wcs_dict)
    x, y = np.indices(w.pixel_shape)
    long, lat = w.pixel_to_world_values(x, y)
    # long, lat from above eqn will always be in degrees, so convert to rad
    long *= _deg_to_rad
    lat *= _deg_to_rad
    if not isinstance(chan_coords, list) and not isinstance(chan_coords, np.ndarray):
        chan_coords = [chan_coords]
    chan_coords = np.array(chan_coords, dtype=np.float64)
    restfreq = chan_coords[len(chan_coords) // 2]
    vel = (1 - chan_coords / restfreq) * _c
    if not isinstance(time_coords, list) and not isinstance(time_coords, np.ndarray):
        time_coords = [time_coords]
    time_coords = np.array(time_coords, dtype=np.float64)
    coords = {
        "time": time_coords,
        "polarization": pol_coords,
        "frequency": chan_coords,
        "velocity": ("frequency", vel),
        "right_ascension": (("l", "m"), long),
        "declination": (("l", "m"), lat),
    }
    xds = xds.assign_coords(coords)
    xds.time.attrs = {"format": "MJD", "scale": "UTC", "unit": "d"}
    xds.frequency.attrs = {
        # "conversion": {
        #    "direction": {
        #        "type": "sky_coord",
        #        "units": ["rad", "rad"],
        #        "frame": "FK5",
        #        "value": np.array([0.0, 1.5707963267948966]),
        #    },
        #    "epoch": {
        #        "units": "d",
        #        "value": 0.0,
        #        "refer": "LAST",
        #        "type": "quantity",
        #    },
        #    "position": {
        #        "units": ["rad", "rad", "m"],
        #        "value": np.array([0.0, 0.0, 0.0]),
        #        "ellipsoid": "GRS80",
        #        "type": "position",
        #    },
        #    "system": spectral_reference.upper(),
        #},
        # "native_type": "FREQ",
        "rest_frequency": {'type': 'quantity', 'units': 'Hz', 'value': restfreq,},
        # "restfreqs":{'type': 'quantity', 'units': 'Hz', 'value': [restfreq],},
        "system": spectral_reference.upper(),
        "unit": "Hz",
        "wave_unit": "mm",
        "crval": chan_coords[len(chan_coords) // 2],
        "cdelt": (chan_coords[1] - chan_coords[0] if len(chan_coords) > 1 else 1000.0),
        "pc": 1.0,
    }
    xds.velocity.attrs = {"doppler_type": "RADIO", "units": "m/s"}
    xds.right_ascension.attrs = {
        "unit": "rad",
        "crval": phase_center[0],
        "cdelt": -abs(cell_size[0]),
    }
    xds.declination.attrs = {
        "unit": "rad",
        "crval": phase_center[1],
        "cdelt": abs(cell_size[1]),
    }
    xds.attrs = {
        "direction": {
            # "conversion_system": direction_reference,
            # "conversion_equinox": "J2000",
            "long_pole": 0.0,
            "lat_pole": 0.0,
            #'pc': np.array([[1.0, 0.0], [0.0, 1.0]]),
            "pc": [[1.0, 0.0], [0.0, 1.0]],
            "projection": projection,
            #'projection_parameters': np.array([0.0, 0.0]),
            "projection_parameters": [0.0, 0.0],
            "system": direction_reference,
            "equinox": "J2000",
        },
        "active_mask": "",
        "beam": None,
        "object_name": "",
        "obsdate": {
            "scale": "UTC",
            "format": "MJD",
            "value": time_coords[0],
            "unit": "d",
        },
        "observer": "Karl Jansky",
        #'pointing_center': {
        #    'value': np.array(phase_center), 'initial': True
        # },
        "pointing_center": {"value": list(phase_center), "initial": True},
        "description": "",
        "telescope": {
            "name": "ALMA",
            "position": {
                "type": "position",
                "ellipsoid": "GRS80",
                "units": ["rad", "rad", "m"],
                "value": np.array(
                    [-1.1825465955049892, -0.3994149869262738, 6379946.01326443]
                ),
            },
        },
        "history": None,
    }
    return xds
