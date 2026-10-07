#!/bin/bash

export PYTHONPATH=/odin/tristan-detector/control/:$PYTHONPATH

DATA_ENDPOINTS=${DATA_ENDPOINTS:-tcp://127.0.0.1:10008,tcp://127.0.0.1:10018,tcp://127.0.0.1:10028,tcp://127.0.0.1:10038,tcp://127.0.0.1:10048,tcp://127.0.0.1:10058,tcp://127.0.0.1:10068,tcp://127.0.0.1:10078}
GRAYLOG_SERVER=${GRAYLOG_SERVER:-localhost:12210}
BEAMLINE=${BEAMLINE:-Tristan}
DETECTOR_NAME=${DETECTOR_NAME:-Tristan10M}

numactl --membind=0 --cpunodebind=0 /odin/bin/meta_writer -w latrd.meta.tristan_meta_writer.TristanMetaWriter -i $DATA_ENDPOINTS --static-log-fields beamline=$BEAMLINE,detector="$DETECTOR_NAME" --log-server "$GRAYLOG_SERVER"
