#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "$0" )" && pwd )"

/odin/bin/tristan_odin --config=$SCRIPT_DIR/odin_server.cfg --logging=error
