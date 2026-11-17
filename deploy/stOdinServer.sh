#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "$0" )" && pwd )"

# Run from this directory so relative paths in odin_server.cfg (e.g. the
# tristan adapter's default udp_file, ./udp_tristan.json) resolve here
cd "$SCRIPT_DIR"

# Increase maximum fds available for ZeroMQ sockets
ulimit -n 2048

/venv/bin/tristan_control --config=$SCRIPT_DIR/odin_server.cfg --logging=error --access_logging=ERROR
