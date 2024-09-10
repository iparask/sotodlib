# Copyright (c) 2018-2020 Simons Observatory.
# Full license can be found in the top level "LICENSE" file.
"""Simons Observatory core routines.

This module has containers and in-memory structures for data and metadata.

"""
from . import util
from .axisman import AxisManager, IndexAxis, LabelAxis, OffsetAxis
from .context import OBSLOADER_REGISTRY, Context
from .flagman import FlagManager
from .hardware import Hardware
from .resources import RESOURCE_DEFAULTS, get_local_file
