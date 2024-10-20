#  CASA Next Generation Infrastructure
#  Copyright (C) 2021, 2023 AUI, Inc. Washington DC, USA
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

import logging
from typing import Any, Dict, List, Tuple, Union

import numpy as np
import xarray as xr

from .msv2_msv3 import ignore_msv2_cols
from .partition_queries import (
    make_partition_ids_by_ddi_intent,
    make_partition_ids_by_ddi_scan,
)
from .subtables import subt_rename_ids, add_pointing_to_partition
from .descr import describe_ms
from ._tables.read import read_generic_table, make_freq_attrs
from ._tables.read_main_table import read_flat_main_table, read_expanded_main_table
from .._utils.partition_attrs import add_partition_attrs
from .._utils.xds_helper import expand_xds, make_coords, optimal_chunking


PartitionKey = Tuple[Any, ...]
VisSetMetaInfo = Dict[str, xr.Dataset]
VisSetPartitions = Dict[PartitionKey, xr.Dataset]


def make_spw_names_by_ddi(ddi_xds: xr.Dataset, spw_xds: xr.Dataset) -> Dict[int, str]:
    spw_ids_by_ddi = ddi_xds.spectral_window_id[ddi_xds.row].values
    spw_names = spw_xds.name[spw_ids_by_ddi].values
    return {ddi: spw_names[ddi] for ddi in np.arange(0, len(spw_names))}


def split_intents(intents: str):
    """Make a dict with two scan / subscan levels of intents from an
    intent string from the STATE/OBS_MODE of an MS.
    """
    sub_sep = "#"
    if sub_sep not in intents:
        sub_sep = "."
        if sub_sep not in intents:
            return intents

    indiv = [intnt for intnt in intents.split(",")]
    scan_subscan_intents = {}
    for ind in indiv:
        scan = ind.split(sub_sep)
        if len(scan) == 1:
            scan = scan[0]
            subscan = ""
        elif len(scan) == 2:
            scan, subscan = scan
        if scan in scan_subscan_intents:
            scan_subscan_intents[scan].append(subscan)
        else:
            scan_subscan_intents[scan] = [subscan]

    return scan_subscan_intents


def make_part_key(
    xds: xr.Dataset,
    partition_scheme: str,
    intent: str = "",
    scan_state: Union[Tuple, None] = None,
):
    """
    Makes the key that a partition (sub)xds will have in the partitions dictionary of a cds.

    :param xds: partition xds with data and attrs
    :param partition_scheme: one of the schemes supported in the read_ms_*_partitions() functions
    :param scan_state: scan/state ids, required when partition_scheme != 'ddi'
    """
    spw_id = xds.attrs["partition_ids"]["spw_id"]
    pol_setup_id = xds.attrs["partition_ids"]["pol_setup_id"]

    if partition_scheme == "ddi":
        part_key = (spw_id, pol_setup_id)
    elif partition_scheme == "intent":
        part_key = (spw_id, pol_setup_id, intent)
    elif partition_scheme == "scan":
        scan, _state = scan_state
        part_key = (spw_id, pol_setup_id, scan)
    elif partition_scheme == "scan/subscan":
        scan, state = scan_state
        part_key = (spw_id, pol_setup_id, scan, state)

    return part_key


def read_ms_scan_subscan_partitions(
    infile: str,
    partition_scheme: str,
    expand: bool = False,
    chunks: Union[Tuple[int], List[int], None] = None,
) -> Tuple[VisSetPartitions, Dict[str, xr.Dataset], List[str]]:
    """partitions per scan_number/subscans
    (main table column SCAN_NUMBER / STATE_ID)

    :param infile: MS path (main table)
    :param partition_scheme: this functions can do 'intent', 'scan', and 'scan/subscan'
    :param expand: wether to use (time, baseline) dimensions rather than 1d (row)
    (only relevant when using the read_flat variant of read functions)
    :param chunk: Dask chunking as tuple (time, baseline, chan, pol)
    :return: a dictionary of partitions, a dict of subtable
    xr.Datasets to use later for metainformation, and a list of the
    subtables already read
    """

    spw_xds = read_generic_table(
        infile,
        "SPECTRAL_WINDOW",
        rename_ids=subt_rename_ids["SPECTRAL_WINDOW"],
    )
    ddi_xds = read_generic_table(infile, "DATA_DESCRIPTION")

    if partition_scheme == "intent":
        spw_names_by_ddi = make_spw_names_by_ddi(ddi_xds, spw_xds)
        (
            data_desc_id,
            scan_number,
            state_id,
            distinct_intents,
        ) = make_partition_ids_by_ddi_intent(infile, spw_names_by_ddi)
    else:
        do_subscans = partition_scheme == "scan/subscan"
        data_desc_id, scan_number, state_id = make_partition_ids_by_ddi_scan(
            infile, do_subscans
        )

    ant_xds = read_generic_table(
        infile, "ANTENNA", rename_ids=subt_rename_ids["ANTENNA"]
    )
    pol_xds = read_generic_table(
        infile, "POLARIZATION", rename_ids=subt_rename_ids["POLARIZATION"]
    )

    # TODO: change to a map?
    partitions = {}
    cnt = 0
    for ddi, scan, state in zip(data_desc_id, scan_number, state_id):
        # msg_chunks = str(chunks[ddi] if type(chunks) == dict else chunks)
        if partition_scheme == "intent":
            intent = distinct_intents[cnt]
            cnt += 1

        if partition_scheme == "scan":
            scan_state = (scan, None)
        else:
            scan_state = (scan, state)
        # experimenting, comparing overheads of expanded vs. flat
        expanded = True
        if expanded:
            xds, part_ids, attrs = read_expanded_main_table(
                infile, ddi, scan_state=scan_state, ignore_msv2_cols=ignore_msv2_cols
            )
        else:
            xds, part_ids, attrs = read_flat_main_table(
                infile,
                ddi,
                scan_state=scan_state,
                rowidxs=None,
                ignore_msv2_cols=ignore_msv2_cols,
            )
        if len(xds.dims) == 0:
            continue

        coords = make_coords(xds, ddi, (ant_xds, ddi_xds, spw_xds, pol_xds))
        xds = xds.assign_coords(coords)

        if partition_scheme == "intent":
            scan_subscan_intents = split_intents(intent)
            attrs = dict({"scan_subscan_intents": scan_subscan_intents}, **attrs)
        xds = add_partition_attrs(xds, ddi, ddi_xds, part_ids, attrs)

        # freq dim needs to pull its units/measure info from the SPW subtable
        spw_id = xds.attrs["partition_ids"]["spw_id"]
        xds.freq.attrs.update(make_freq_attrs(spw_xds, spw_id))

        # expand the row dimension out to (time, baseline)
        if not expanded and expand:
            xds = expand_xds(xds)

        part_key = make_part_key(
            xds, partition_scheme, scan_state=scan_state, intent=intent
        )
        partitions[part_key] = xds

    subtables = {
        "antenna": ant_xds,
        "spectral_window": spw_xds,
        "polarization": pol_xds,
    }

    return (
        partitions,
        subtables,
        ["ANTENNA", "SPECTRAL_WINDOW", "POLARTIZATION", "DATA_DESCRIPTION"],
    )


def read_ms_ddi_partitions(
    infile: str,
    expand: bool = False,
    rowmap: Union[dict, None] = None,
    chunks: Union[Tuple[int], List[int], None] = None,
) -> Tuple[VisSetPartitions, Dict[str, xr.Dataset], List[str]]:
    """
    Reads data columns from the main table into partitions defined
    from the DDIs. First looks into the SPECTRAL_WINDOW, POLARIZATION,
    DATA_DESCRIPTION tables to define the partitions.

    :param expand: redimension (row)->(time,baseline)
    :param rowmap: to be removed
    :param chunks: array data chunk sizes
    :return: dictionary of partitions, dict of subtable xr.Datasets to use later
    for metainformation, and a list of the subtables already read
    """
    # we need the antenna, spectral window, polarization, and data description tables
    # to define the (sub)datasets (their dims and coords) and to process the main table
    ant_xds = read_generic_table(
        infile, "ANTENNA", rename_ids=subt_rename_ids["ANTENNA"]
    )
    spw_xds = read_generic_table(
        infile,
        "SPECTRAL_WINDOW",
        rename_ids=subt_rename_ids["SPECTRAL_WINDOW"],
    )
    pol_xds = read_generic_table(
        infile, "POLARIZATION", rename_ids=subt_rename_ids["POLARIZATION"]
    )
    ddi_xds = read_generic_table(infile, "DATA_DESCRIPTION")

    # each DATA_DESC_ID (ddi) is a fixed shape that may differ from others
    # form a list of ddis to process, each will be placed it in its own xarray dataset and partition
    ddis = np.arange(ddi_xds.row.shape[0]) if rowmap is None else list(rowmap.keys())

    # figure out the chunking for each DDI, either one fixed shape or an auto-computed one
    if type(chunks) != tuple:
        mshape = describe_ms(infile, mode="flat", rowmap=rowmap)
        chunks = dict(
            [
                (
                    ddi,
                    optimal_chunking(
                        didxs=chunks, chunk_size="auto", data_shape=mshape[ddi]
                    ),
                )
                for ddi in mshape
            ]
        )

    partitions = {}
    ####################################################################
    # process each selected DDI from the input MS, assume a fixed shape within the ddi (should always be true)
    for ddi in ddis:
        rowidxs = None if rowmap is None else rowmap[ddi][0]
        chanidxs = None if rowmap is None else rowmap[ddi][1]
        if ((rowidxs is not None) and (len(rowidxs) == 0)) or (
            (chanidxs is not None) and (len(chanidxs) == 0)
        ):
            continue
        logging.debug(
            "reading DDI %i with chunking %s..."
            % (ddi, str(chunks[ddi] if type(chunks) == dict else chunks))
        )

        # experimenting, comparing overheads of expanded vs. flat
        expanded = True
        if expanded:
            xds, part_ids, attrs = read_expanded_main_table(
                infile, ddi, ignore_msv2_cols=ignore_msv2_cols
            )
        else:
            xds, part_ids, attrs = read_flat_main_table(
                infile,
                ddi,
                rowidxs=rowidxs,
                chunks=chunks[ddi] if type(chunks) == dict else chunks,
                ignore_msv2_cols=ignore_msv2_cols,
            )
        if len(xds.dims) == 0:
            continue

        coords = make_coords(xds, ddi, (ant_xds, ddi_xds, spw_xds, pol_xds))
        xds = xds.assign_coords(coords)

        xds = add_partition_attrs(xds, ddi, ddi_xds, part_ids, attrs)

        # freq dim needs to pull its units/measure info from the SPW subtable
        spw_id = xds.attrs["partition_ids"]["spw_id"]
        xds.freq.attrs.update(make_freq_attrs(spw_xds, spw_id))

        # filter by channel selection
        if (chanidxs is not None) and (len(chanidxs) < len(xds.chan)):
            xds = xds.isel(chan=chanidxs)
            spw_xds["chan_freq"][
                ddi_xds.spectral_window_id.values[ddi], : len(chanidxs)
            ] = spw_xds.chan_freq[ddi_xds.spectral_window_id.values[ddi], chanidxs]

        # expand the row dimension out to (time, baseline)
        if not expanded and expand:
            xds = expand_xds(xds)

        part_key = make_part_key(xds, partition_scheme="ddi")
        partitions[part_key] = xds

    subtables = {
        "antenna": ant_xds,
        "spectral_window": spw_xds,
        "polarization": pol_xds,
        "data_description": ddi_xds,
    }

    return (
        partitions,
        subtables,
        ["ANTENNA", "SPECTRAL_WINDOW", "POLARTIZATION", "DATA_DESCRIPTION"],
    )


def finalize_partitions(
    parts: Dict[str, xr.Dataset], subts: Dict[str, xr.Dataset]
) -> Dict[str, xr.Dataset]:
    """Once the partition datasets and the metainfo/subtable datasets
    have been read, add to the partitions:
    - pointing variables from the pointing subtable

    :param parts: partitions as xarray datasets, as read from an MS main table
    :param subts: subtables of an MS read as xarray datasets
    :return: partitions with additions taken from subtables
    """
    if "pointing" in subts:
        pointing = subts["pointing"]
        final = {
            key: add_pointing_to_partition(xds, pointing)
            for (key, xds) in parts.items()
        }
    else:
        final = parts

    return final
