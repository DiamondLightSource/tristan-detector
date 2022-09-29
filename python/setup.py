
import sys

from setuptools import setup

sys.path.append(".")  # pipenv install fails without this - pip install works fine
import versioneer

setup(
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass()
)
