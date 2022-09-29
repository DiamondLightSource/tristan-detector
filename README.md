
Tristan Detector

Python Control Software Instructions
==========================================

System dependencies:

    Python3
    pip - python package manager
    ZeroMQ (development package)

Building with setuptools will attempt to use pip to download and install dependencies locally first. The python dependencies are listed in control_requirements.txt

To install the example control script and simulator

    virtualenv -p <path to python3> --no-site-packages venv3
    source venv3/bin/activate
    pip install --upgrade pip
    pip install --upgrade virtualenv
    pip install -r control_requirements.txt
    python setup.py install

To execute the simulator

    source venv3/bin/activate
    tristan-simulator

and to run the example test client script

    source venv3/bin/activate
    test-control-interface

note that the static directory is necessary for odin_control, and is packaged as part of the wheel for convenience,
but you should MOVE it from your virtual environment to a position close to your odin-tristan.cfg file.
eg. venv3/lib/python3.7/site-packages/tristan-detector/static to ~/tristan/static



Build Instructions
==================

	mkdir builddir
	cd builddir
	cmake -DBoost_NO_BOOST_CMAKE=ON \
	      -DLOG4CXX_ROOT_DIR=/dls_sw/prod/tools/RHEL7-x86_64/log4cxx/version/prefix \
	      -DZEROMQ_ROOTDIR=/dls_sw/prod/tools/RHEL7-x86_64/zeromq/version/prefix \
	      -DODINDATA_ROOT_DIR=/home/gnx91527/work/odin-data/build \
	      -DHDF5_ROOT=/dls_sw/prod/tools/RHEL7-x86_64/hdf5/version/prefix \
	      ..

