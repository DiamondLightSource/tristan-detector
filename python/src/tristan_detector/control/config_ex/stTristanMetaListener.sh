#!/bin/bash

cd /dls_sw/prod/tools/RHEL7-x86_64/odin-data/1-4-0dls3
export PYTHONPATH=/dls_sw/work/tools/RHEL7-x86_64/tristan-detector/control/
prefix/bin/meta_writer -w latrd.meta.tristan_meta_writer.TristanMetaWriter -i tcp://127.0.0.1:10008,tcp://127.0.0.1:10018,tcp://127.0.0.1:10028,tcp://127.0.0.1:10038,tcp://127.0.0.1:10048,tcp://127.0.0.1:10058,tcp://127.0.0.1:10068,tcp://127.0.0.1:10078 --staticlogfields beamline=${BEAMLINE},detector="Tristan10M" --logserver "graylog2.diamond.ac.uk:12210"
