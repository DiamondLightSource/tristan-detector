# Tristan Detector

Data acquisition framework for the Tristan detector using [odin-data].

## Python Control Software Instructions

System dependencies:

    Python3
    pip - python package manager
    ZeroMQ (development package)

To install the example control script and simulator

    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -e ./python

To execute the tristan control server

    tristan_control

To execute the tristan meta writer

    tristan_meta_writer

To execute the simulator

    tristan_simulator

## C++ Build Instructions

A [devcontainer] is provided for simpler local development. `odin-data` is
pre-installed in `/odin` and there are vscode settings to build `tristan-detector`
against this. Follow the steps below to get started.

1. Open the project in VSCode and re-open in devcontainer when prompted, or
   open manually with `> Dev Containers: Reopen in Container`
2. Install the recommended extensions for the workspace
    (`> Extensions: Show Recommended Extensions`)
3. Build tristan-detector

    i. `> CMake: Delete Cache and Reconfigure` (select gcc version in dropdown)

    ii. `> CMake: Install`

To build from the command line:

    mkdir builddir
    cd builddir
    cmake -DBoost_NO_BOOST_CMAKE=ON \
          -DLOG4CXX_ROOT_DIR=$LOG4CXX_ROOT_DIR \
          -DZEROMQ_ROOTDIR=$ZEROMQ_ROOTDIR \
          -DODINDATA_ROOT_DIR=$ODINDATA_ROOT_DIR \
          -DHDF5_ROOT=$HDF5_ROOT \
          ..

where each variable points to the corresponding installation prefix.

## Related Projects

- [fastcs-odin]: An EPICS driver to control the odin-data / tristan-detector applications
- [odin-data]: The odin-data framework

[odin-data]: https://github.com/odin-detector/odin-data
[fastcs-odin]: https://github.com/DiamondLightSource/fastcs-odin
[devcontainer]: https://code.visualstudio.com/docs/devcontainers/containers
