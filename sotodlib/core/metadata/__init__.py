# Copyright (c) 2018-2020 Simons Observatory.
# Full license can be found in the top level "LICENSE" file.
"""Metadata containers.
"""

from . import cli
from .detdb import DetDb
from .loader import (LoaderInterface, MetadataSpec, SuperLoader, load_metadata,
                     merge_det_info)
from .manifest import ManifestDb, ManifestScheme
from .obsdb import ObsDb
from .obsfiledb import ObsFileDb
from .resultset import ResultSet


def get_example(db_type, *args, **kwargs):
    if db_type == "DetDb":
        from .detdb import get_example

        return get_example(*args, **kwargs)
    else:
        raise ValueError("Unknown db_type: %s" % db_type)
