
from tristan_detector._version import get_versions
from tristan_detector.control.tristan_adapter import TristanControlAdapter
from tristan_detector.data.tristan_meta_writer import TristanMetaWriter

__version__ = get_versions()["version"]
del get_versions

__all__ = ["TristanControlAdapter", "TristanMetaWriter", "__version__"]
