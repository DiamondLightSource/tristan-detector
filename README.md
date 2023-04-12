# Tristan Detector

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

	mkdir builddir
	cd builddir
	cmake -DBoost_NO_BOOST_CMAKE=ON \
	      -DLOG4CXX_ROOT_DIR=/dls_sw/prod/tools/RHEL7-x86_64/log4cxx/version/prefix \
	      -DZEROMQ_ROOTDIR=/dls_sw/prod/tools/RHEL7-x86_64/zeromq/version/prefix \
	      -DODINDATA_ROOT_DIR=/home/gnx91527/work/odin-data/build \
	      -DHDF5_ROOT=/dls_sw/prod/tools/RHEL7-x86_64/hdf5/version/prefix \
	      ..

