"""Implementation of meta writer for Tristan

This module is a subclass of the odin_data MetaWriter and handles Tristan specific
meta data messages, writing them to disk
"""

import struct
from collections import OrderedDict

from odin_data.meta_writer.hdf5dataset import Int32HDF5Dataset
from odin_data.meta_writer.meta_writer import MetaWriter, require_open_hdf5_file

# from . import _version as versioneer

# Dataset names
DATASET_TIME_SLICE = "ts_qty_module"
DATASET_DAQ_VERSION = "data_version"
DATASET_META_VERSION = "meta_version"
DATASET_FP_PER_MODULE = "fp_per_module"

# Data message parameters
TIME_SLICE = "time_slice"
DAQ_VERSION = "daq_version"

# Meta file version
# Version 1: First revision
#            Table for each FP time slice count.
#            No version information saved.
#
# Version 2: DAQ version and Meta file version saved.
#            Table for each server with condensed time slice information.
META_VERSION_NUMBER = 1


class TristanMetaWriter(MetaWriter):
    """Implementation of MetaWriter that also handles Tristan meta messages"""

    def __init__(self, name, directory, endpoints, writer_config):

        # Create ordered dict to store FP mapping entries
        self._fp_mapping = OrderedDict()
        self._time_slice_index_offset = None
        self._fps_per_module = []
        self._max_index_per_module = []
        for endpoint in endpoints:
            protocol, ip, port = endpoint.split(":")
            ip = ip.removeprefix("//")
            if ip in self._fp_mapping:
                self._fp_mapping[ip] += 1
            else:
                self._fp_mapping[ip] = 1

        for ip in self._fp_mapping:
            self._fps_per_module.append(self._fp_mapping[ip])

        # Now that we have defined the datasets we can call the base class constructor
        super().__init__(name, directory, endpoints, writer_config)

        # Log the current endpoint configuration
        self._logger.info(f"Set up Tristan writer for endpoints: {endpoints}")

    @property
    def detector_message_handlers(self):
        message_handlers = {
            TIME_SLICE: self.handle_time_slice,
            DAQ_VERSION: self.handle_daq_version,
        }
        return message_handlers

    def _define_detector_datasets(self):
        # Create the tristan specific datasets
        datasets = [
            Int32HDF5Dataset(DATASET_DAQ_VERSION),
            Int32HDF5Dataset(DATASET_META_VERSION),
            Int32HDF5Dataset(DATASET_FP_PER_MODULE),
        ]

        for index in range(len(self._fp_mapping)):
            datasets.append(
                Int32HDF5Dataset(f"{DATASET_TIME_SLICE}{index:02d}", fillvalue=0)
            )

        for dset in datasets:
            self._logger.info(f"Tristan dataset added: {dset.name} [{dset.dtype}]")
        return datasets

    @require_open_hdf5_file
    def _close_file(self):
        self._logger.info(
            f"Current timeslice offsets at file close: {self._max_index_per_module}"
        )
        # Find the maximum size of timeslice dataset over all modules
        max_ts_index = max(self._max_index_per_module)
        # Now loop over all modules and increase the size of each timeslice dataset
        # to the same as the maximum to eliminate ragged edges
        for index in range(len(self._max_index_per_module)):
            # Check if this is not the maximum sized dataset
            if self._max_index_per_module[index] < max_ts_index:
                # Generate the dataset name
                dataset_name = f"{DATASET_TIME_SLICE}{index:02d}"
                # Fill dataset with zero values up to maximum dataset size
                self._add_value(dataset_name, 0, offset=max_ts_index)

        # Now complete the closing of the file
        super()._close_file()

    @require_open_hdf5_file
    def _create_datasets(self, dataset_size):
        super()._create_datasets(dataset_size)
        self._logger.info("Hooked into create datasets...")
        # Save the Met File version
        self._add_value(DATASET_META_VERSION, META_VERSION_NUMBER, offset=0)
        # Save the FP mapping values, create the maximum saved index list
        index = 0
        for ip in self._fp_mapping:
            self._add_value(DATASET_FP_PER_MODULE, self._fp_mapping[ip], offset=index)
            self._max_index_per_module.append(0)
            index += 1

    def rank_to_module(self, rank):
        module = 0
        for ip in self._fp_mapping:
            if rank >= self._fp_mapping[ip]:
                module += 1
                rank -= self._fp_mapping[ip]
        self._logger.debug(f"Rank {rank} calculated to module {module}")
        return module

    def handle_time_slice(self, user_header, data):
        """Handle a time slice message.  Write the time slice information
        to disk and generate any required VDS files

        :param user_header: The header
        :param value: An array of time slice sizes
        """
        self._logger.debug(f"handle_time_slice | User information: {user_header}")

        # Extract the rank and array size information from the header
        rank = user_header["rank"]
        index = user_header["index"]
        array_size = user_header["qty"]
        format_str = f"{array_size}i"
        array = struct.unpack(format_str, data)
        self._logger.debug(f"Rank: {rank}  Index {index}  Array_Size {array_size}")
        self._logger.debug(array)
        module = self.rank_to_module(rank)

        dataset_name = f"{DATASET_TIME_SLICE}{module:02d}"
        # Now loop over provided data, and write any non-zero values
        for array_index in range(len(array)):
            if array[array_index] > 0:
                offset = index + array_index
                if self._time_slice_index_offset is None:
                    self._time_slice_index_offset = rank - offset
                    while self._time_slice_index_offset < 0:
                        self._time_slice_index_offset += self._fps_per_module[module]
                    while self._time_slice_index_offset > self._fps_per_module[module]:
                        self._time_slice_index_offset -= self._fps_per_module[module]
                    self._logger.info(
                        f"Rank {rank}  Index {offset} "
                        f"Time slice offset {self._time_slice_index_offset}"
                    )
                offset += self._time_slice_index_offset
                if offset < 0:
                    self._logger.error(
                        "Attempting to write a value with a negative offset - "
                        f"Rank: {rank} Offset: {offset} "
                        f"Time slice offset: {self._time_slice_index_offset}"
                    )
                self._logger.debug(
                    f"Adding value {array[array_index]} to offset {offset}"
                )
                self._add_value(dataset_name, array[array_index], offset=offset)
                if offset > self._max_index_per_module[module]:
                    self._max_index_per_module[module] = offset

    def handle_daq_version(self, user_header, data):
        """Handle a time slice message.  Write the time slice information
        to disk and generate any required VDS files

        :param user_header: The header
        :param value: An array of time slice sizes
        """
        self._logger.debug(f"handle_daq_version | User information: {user_header}")

        # Extract the rank information from the header
        rank = user_header["rank"]
        value = struct.unpack("i", data)[0]
        self._logger.debug(f"Rank: {rank}  Version: {value}")
        self._add_value(DATASET_DAQ_VERSION, value, offset=rank)
