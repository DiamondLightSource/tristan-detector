#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "$0" )" && pwd )"

export HDF5_PLUGIN_PATH=/odin/h5plugin

/odin/bin/frameProcessor --ctrl=tcp://0.0.0.0:10064 --ready=tcp://127.0.0.1:10061 --release=tcp://127.0.0.1:10062 --json_file=$SCRIPT_DIR/fp47.json --logconfig $SCRIPT_DIR/log4cxx.xml
