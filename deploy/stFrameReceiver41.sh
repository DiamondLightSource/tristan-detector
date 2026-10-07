#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "$0" )" && pwd )"

/odin/bin/frameReceiver --sharedbuf=odin_buf_1 -m 70000000000 --iothreads 1 --ctrl=tcp://0.0.0.0:10000 --ready=tcp://127.0.0.1:10001 --release=tcp://127.0.0.1:10002 --json_file=$SCRIPT_DIR/fr41.json --logconfig $SCRIPT_DIR/log4cxx.xml
