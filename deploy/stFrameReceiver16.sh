#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "$0" )" && pwd )"

/odin/bin/frameReceiver --sharedbuf=odin_buf_6 -m 70000000000 --iothreads 1 --ctrl=tcp://0.0.0.0:10050 --ready=tcp://127.0.0.1:10051 --release=tcp://127.0.0.1:10052 --json_file=$SCRIPT_DIR/fr16.json --logconfig $SCRIPT_DIR/log4cxx.xml
