import pandas as pd
from xradio._utils.list_and_array import to_list
import xarray as xr
import numpy as np
import numbers
import os
from collections.abc import Mapping, Iterable
from typing import Any, Union

MS_DATASET_TYPES = {"visibility", "spectrum", "wvr"}


class InvalidAccessorLocation(ValueError):
    pass


@xr.register_datatree_accessor("ms")
class MeasurementSetXdt:
    _xdt: xr.DataTree

    def __init__(self, datatree: xr.DataTree):
        """
        Initialize the MeasurementSetXdt instance.

        Parameters
        ----------
        """

        self._xdt = datatree
        self.meta = {"summary": {}}

    def sel(
        self,
        indexers: Union[Mapping[Any, Any], None] = None,
        method: Union[str, None] = None,
        tolerance: Union[int, float, Iterable[Union[int, float]], None] = None,
        drop: bool = False,
        **indexers_kwargs: Any,
    ):
        """
        Select data along dimension(s) by label. Alternative to `xarray.Dataset.sel <https://xarray.pydata.org/en/stable/generated/xarray.Dataset.sel.html>`__ so that a data group can be selected by name by using the `data_group_name` parameter.
        For more information on data groups see `Data Groups <https://xradio.readthedocs.io/en/latest/measurement_set_overview.html#Data-Groups>`__ section. See `xarray.Dataset.sel <https://xarray.pydata.org/en/stable/generated/xarray.Dataset.sel.html>`__ for parameter descriptions.

        Returns:
            Xdt with MeasurementSetXdt Assessors

        Examples
        --------
        >>> # Select data group 'corrected' and polarization 'XX'.
        >>> selected_ms_xdt = ms_xdt.sel(data_group_name='corrected', polarization='XX')

        >>> # Select data group 'corrected' and polarization 'XX' using a dict.
        >>> selected_ms_xdt = ms_xdt.sel({'data_group_name':'corrected', 'polarization':'XX')
        """

        if self._xdt.attrs.get("type") not in MS_DATASET_TYPES:
            raise InvalidAccessorLocation(f"{self._xdt.path} is not a MSv4node. ")

        assert (self._xdt.attrs["type"] == "visibility") or (
            self._xdt.attrs["type"] == "spectrum"
        ), "The type of the xdt must be 'visibility' or 'spectrum'."

        if "data_group_name" in indexers_kwargs:
            data_group_name = indexers_kwargs["data_group_name"]
            del indexers_kwargs["data_group_name"]
        elif (indexers is not None) and ("data_group_name" in indexers):
            data_group_name = indexers["data_group_name"]
            del indexers["data_group_name"]
        else:
            data_group_name = None

        if data_group_name is not None:
            sel_data_group_set = set(
                self._xdt.attrs["data_groups"][data_group_name].values()
            )

            data_variables_to_drop = []
            for dg in self._xdt.attrs["data_groups"].values():
                temp_set = set(dg.values()) - sel_data_group_set
                data_variables_to_drop.extend(list(temp_set))

            data_variables_to_drop = list(set(data_variables_to_drop))

            sel_ms_xdt = self._xdt

            sel_corr_xds = self._xdt.ds.sel(
                indexers, method, tolerance, drop, **indexers_kwargs
            ).drop_vars(data_variables_to_drop)

            sel_ms_xdt.ds = sel_corr_xds

            sel_ms_xdt.attrs["data_groups"] = {
                data_group_name: self._xdt.attrs["data_groups"][data_group_name]
            }

            return sel_ms_xdt
        else:
            return self._xdt.sel(indexers, method, tolerance, drop, **indexers_kwargs)

    def get_field_and_source_xds(self, data_group_name=None) -> xr.Dataset:
        """Get the field_and_source_xds associated with data group `data_group_name`.

        Parameters
        ----------
        data_group_name : str, optional
            The data group to process. Default is "base" or if not found to first data group.

        Returns
        -------
        xr.Dataset
            field_and_source_xds associated with the data group.

        """
        if self._xdt.attrs.get("type") not in MS_DATASET_TYPES:
            raise InvalidAccessorLocation(f"{self._xdt.path} is not a MSv4node. ")

        if data_group_name is None:
            if "base" in self._xdt.attrs["data_groups"].keys():
                data_group_name = "base"
            else:
                data_group_name = list(self._xdt.attrs["data_groups"].keys())[0]

        return self._xdt[f"field_and_source_xds_{data_group_name}"].ds

    def get_partition_info(self) -> dict:
        if self._xdt.attrs.get("type") not in MS_DATASET_TYPES:
            raise InvalidAccessorLocation(f"{self._xdt.path} is not a MSv4node. ")

        field_and_source_xds = self._xdt.ms.get_field_and_source_xds()

        if "line_name" in field_and_source_xds.coords:
            line_name = to_list(
                np.unique(np.ravel(field_and_source_xds.line_name.values))
            )
        else:
            line_name = []

        partition_info = {
            "spectral_window_name": self._xdt.frequency.attrs["spectral_window_name"],
            "field_name": to_list(np.unique(field_and_source_xds.field_name.values)),
            "polarization_setup": to_list(self._xdt.polarization.values),
            "scan_name": to_list(np.unique(self._xdt.scan_name.values)),
            "source_name": to_list(np.unique(field_and_source_xds.source_name.values)),
            "intents": self._xdt.observation_info["intents"],
            "line_name": line_name,
        }

        return partition_info


# class MeasurementSetXdt(xr.Dataset):
#     __slots__ = ()

#     def __init__(self, xds):
#         super().__init__(xds.data_vars, xds.coords, xds.attrs)

#     def to_store(self, store, **kwargs):
#         """
#         Write the MeasurementSetXds to a Zarr store.
#         Does not write to cloud storage yet.

#         Args:
#             store (str): The path to the Zarr store.
#             **kwargs: Additional keyword arguments to be passed to `xarray.Dataset.to_zarr`. See https://docs.xarray.dev/en/latest/generated/xarray.Dataset.to_zarr.html for more information.

#         Returns:
#             None
#         """

#         copy_cor_xds = self.copy()  # No deep copy

#         # Remove field_and_source_xds from all correlated_data (VISIBILITY/SPECTRUM) data variables
#         # and save them as separate zarr files.
#         for data_group_name, data_group in self.attrs["data_groups"].items():
#             del copy_cor_xds[data_group["correlated_data"]].attrs[
#                 "field_and_source_xds"
#             ]

#             # print("data_group_name", data_group_name)
#             xr.Dataset.to_zarr(
#                 self[data_group["correlated_data"]].attrs["field_and_source_xds"],
#                 os.path.join(store, "field_and_source_xds_" + data_group_name),
#                 **kwargs,
#             )

#         # Remove xds attributes from copy_cor_xds and save xds attributes as separate zarr files.
#         for attrs_name in self.attrs:
#             if "xds" in attrs_name:
#                 del copy_cor_xds.attrs[attrs_name]
#                 xr.Dataset.to_zarr(
#                     self.attrs[attrs_name], os.path.join(store, attrs_name), **kwargs
#                 )

#         # Save copy_cor_xds as zarr file.
#         xr.Dataset.to_zarr(
#             copy_cor_xds, os.path.join(store, "correlated_xds"), **kwargs
#         )

#     def sel(
#         self,
#         indexers: Union[Mapping[Any, Any], None] = None,
#         method: Union[str, None] = None,
#         tolerance: Union[int, float, Iterable[Union[int, float]], None] = None,
#         drop: bool = False,
#         **indexers_kwargs: Any,
#     ):
#         """
#         Select data along dimension(s) by label. Overrides `xarray.Dataset.sel <https://xarray.pydata.org/en/stable/generated/xarray.Dataset.sel.html>`__ so that a data group can be selected by name by using the `data_group_name` parameter.
#         For more information on data groups see `Data Groups <https://xradio.readthedocs.io/en/latest/measurement_set_overview.html#Data-Groups>`__ section. See `xarray.Dataset.sel <https://xarray.pydata.org/en/stable/generated/xarray.Dataset.sel.html>`__ for parameter descriptions.

#         Returns:
#             MeasurementSetXds

#         Examples
#         --------
#         >>> # Select data group 'corrected' and polarization 'XX'.
#         >>> selected_ms_xds = ms_xds.sel(data_group_name='corrected', polarization='XX')

#         >>> # Select data group 'corrected' and polarization 'XX' using a dict.
#         >>> selected_ms_xds = ms_xds.sel({'data_group_name':'corrected', 'polarization':'XX')
#         """

#         if "data_group_name" in indexers_kwargs:
#             data_group_name = indexers_kwargs["data_group_name"]
#             del indexers_kwargs["data_group_name"]
#         elif (indexers is not None) and ("data_group_name" in indexers):
#             data_group_name = indexers["data_group_name"]
#             del indexers["data_group_name"]
#         else:
#             data_group_name = None

#         if data_group_name is not None:
#             sel_data_group_set = set(
#                 self.attrs["data_groups"][data_group_name].values()
#             )

#             data_variables_to_drop = []
#             for dg in self.attrs["data_groups"].values():
#                 temp_set = set(dg.values()) - sel_data_group_set
#                 data_variables_to_drop.extend(list(temp_set))

#             data_variables_to_drop = list(set(data_variables_to_drop))

#             sel_ms_xds = MeasurementSetXds(
#                 super()
#                 .sel(indexers, method, tolerance, drop, **indexers_kwargs)
#                 .drop_vars(data_variables_to_drop)
#             )

#             sel_ms_xds.attrs["data_groups"] = {
#                 data_group_name: self.attrs["data_groups"][data_group_name]
#             }

#             return sel_ms_xds
#         else:
#             return MeasurementSetXds(
#                 super().sel(indexers, method, tolerance, drop, **indexers_kwargs)
#             )
