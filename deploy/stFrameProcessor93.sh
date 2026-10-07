#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "$0" )" && pwd )"

export HDF5_PLUGIN_PATH=/odin/h5plugin

/odin/bin/frameProcessor --ctrl=tcp://0.0.0.0:10024 --ready=tcp://127.0.0.1:10021 --release=tcp://127.0.0.1:10022 --json_file=$SCRIPT_DIR/fp93.json --logconfig $SCRIPT_DIR/log4cxx.xml
