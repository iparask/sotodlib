"""Utility functions for interacting with level 2 data and g3tsmurf
"""

import os
import numpy as np
import logging
import yaml

from so3g.hk import load_range

import sotodlib.core as core
from sotodlib.io.load_smurf import load_file, SmurfStatus
from sotodlib.io.g3tsmurf_db import Observations, Files
from scipy.interpolate import interp1d

logger = logging.getLogger(__name__)


def get_obs_folder(obs_id, archive):
    """
    Get the folder associated with the observation action. Assumes
    everything is following the standard suprsync formatting.
    """
    session = archive.Session()
    obs = session.query(Observations).\
        filter(Observations.obs_id == obs_id).one()
    session.close()

    return os.path.join(
        archive.meta_path,
        str(obs.action_ctime)[:5],
        obs.stream_id,
        str(obs.action_ctime)+"_"+obs.action_name,
    )


def get_obs_outputs(obs_id, archive):
    """
    Get the output files associated with the observation action. Assumes
    everything is following the standard suprsync formatting. Returns
    absolute paths since everything in g3tsmurf is absolute paths.
    """
    path = os.path.join(
        get_obs_folder(obs_id, archive),
        "outputs"
    )

    if not os.path.exists(path):
        logger.error(f"Path {path} does not exist, " +
                     f"how does {obs.obs_id} exist?")
    return [os.path.join(path, f) for f in os.listdir(path)]


def get_obs_plots(obs_id, archive):
    """
    Get the output plots associated with the observation action. Assumes
    everything is following the standard suprsync formatting. Returns
    absolute paths since everything in g3tsmurf is absolute paths.
    """
    path = os.path.join(
        get_obs_folder(obs_id, archive),
        "plots"
    )

    if not os.path.exists(path):
        logger.error(f"Path {path} does not exist, " +
                     f"how does {obs.obs_id} exist?")
    return [os.path.join(path, f) for f in os.listdir(path)]


def get_batch(
    obs_id,
    archive,
    ram_limit=None,
    n_det_chunks=None,
    n_samp_chunks=None,
    n_dets=None,
    n_samps=None,
    det_chunks=None,
    samp_chunks=None,
    test=False,
    load_file_args={},
):
    """A Generator to loop through and load AxisManagers of sections of
    Observations. When run with none of the optional arguments it will default
    to returning the full observation. Some arguments over-write others as
    described in the docstrings below. When splitting the Observations by both
    detectors and samples, the chunks of samples for the same detectors are
    looped through first (samples is the inner for loop).

    Example usage::

        for aman in get_batch(obs_id, archive, ram_limit=2e9):
            run_analysis_pipeline(aman)

        for aman in get_batch(obs_id, archive, n_dets=200):
            run_analysis_pipeline(aman)


    Arguments
    ----------
    obs_id : string
        Level 2 observation IDs
    archive : G3tSmurf Instance
        The G3tSmurf database connected to the obs_id
    ram_limit : None or float
        A (very simplistically calculated) limit on RAM per AxisManager. If
        specified it overrides all other inputs for how the AxisManager is
        split.
    n_det_chunks : None or int
        number of chunks of detectors to split the observation by. Each
        AxisManager will have N_det = N_obs_det / n_det_chunks. If specified,
        it overrides n_dets and det_chunks arguments.
    n_samp_chunks: None or int
        number of chunks of samples to split the observation by. Each
        AxisManage will have N_samps = N_obs_samps / n_samps_chunks. If
        specified, it overrides n_samps and samp_chunks arguments.
    n_dets : None or int
        number of detectors to load per AxisManager. If specified, it overrides
        the det_chunks argument.
    n_samps : None or int
        number of samples to load per AxisManager. If specified it overrides
        the samps_chunks arguments.
    det_chunks: None or list of lists, tuples, or ranges
        if specified, each entry in the list is successively passed to load the
        AxisManagers as  `load_file(... channels = list[i] ... )`
    samp_chunks: None or list of tuples
        if specified, each entry in the list is successively passed to load the
        AxisManagers as  `load_file(... samples = list[i] ... )`
    test: bool
        If true, yields a tuple of (det_chunks, samp_chunks) instead of a
        loaded AxisManager
    load_file_kwargs: dict
        additional arguments to pass to load_smurf

    Yields
    --------
    AxisManagers with loaded sections of data
    """

    session = archive.Session()
    obs = session.query(Observations).\
        filter(Observations.obs_id == obs_id).one()
    db_files = session.query(Files).\
        filter(Files.obs_id == obs_id).order_by(Files.start)
    filenames = sorted([f.name for f in db_files])

    # if this throws an error we have some fallbacks
    ts = obs.tunesets[0]
    obs_dets, obs_samps = len(ts.dets), obs.n_samples
    session.close()

    if n_det_chunks is not None and n_dets is not None:
        logger.warning("Both n_det_chunks and n_dets specified, " +
                       "n_det_chunks overrides")
    if n_samp_chunks is not None and n_samps is not None:
        logger.warning("Both n_samp_chunks and n_samps specified, " +
                       "n_samp_chunks overrides")

    logger.debug(f"{obs_id} has (n_dets, n_samps): ({obs_dets}, {obs_samps})")
    if ram_limit is not None:
        pts_limit = int(ram_limit // 4)
        n_samp_chunks = 1
        n_samps = obs_samps
        n_dets = pts_limit // n_samps
        while n_dets == 0:
            n_samp_chunks += 1
            n_samps = obs_samps//n_samp_chunks
            n_dets = pts_limit // (n_samps)
        n_det_chunks = int(np.ceil(obs_dets/n_dets))

    if n_det_chunks is not None:
        n_dets = int(np.ceil(obs_dets/n_det_chunks))
        det_chunks = [range(i*n_dets, min((i+1)*n_dets, obs_dets))
                      for i in range(n_det_chunks)]
    if n_samp_chunks is not None:
        n_samps = int(np.ceil(obs_samps/n_samp_chunks))
        samp_chunks = [(i*n_samps, min((i+1)*n_samps, obs_samps))
                       for i in range(n_samp_chunks)]

    if n_dets is not None:
        n_det_chunks = int(np.ceil(obs_dets/n_dets))
        det_chunks = [range(i*n_dets, min((i+1)*n_dets, obs_dets))
                      for i in range(n_det_chunks)]
    if n_samps is not None:
        n_samp_chunks = int(np.ceil(obs_samps/n_samps))
        samp_chunks = [(i*n_samps, min((i+1)*n_samps, obs_samps))
                       for i in range(n_samp_chunks)]

    if det_chunks is None:
        det_chunks = [range(0, obs_dets)]
    if samp_chunks is None:
        samp_chunks = [(0, obs_samps)]

    # should we let folks overwrite this here?
    if "archive" in load_file_args:
        archive = load_file_args.pop("archive")

    if "status" in load_file_args:
        status = load_file_args.pop("status")
    else:
        status = SmurfStatus.from_file(filenames[0])

    logger.debug(f"Loading data with det_chunks: {det_chunks}.")
    logger.debug(f"Loading data in samp_chunks: {samp_chunks}.")

    try:
        for det_chunk in det_chunks:
            for samp_chunk in samp_chunks:
                if test:
                    yield (det_chunk, samp_chunk)
                else:
                    yield load_file(
                        filenames,
                        channels=det_chunk,
                        samples=samp_chunk,
                        archive=archive,
                        status=status,
                        **load_file_args,
                    )
    except GeneratorExit:
        pass

def remove_detmap_info(aman):
    aman.det_info.move("det_id", None)
    aman.det_info.move("wafer", None)

    
def replace_none(val, dtype, replace_val=np.nan):
    if dtype == str and (val == "null" or val == "NC"):
        return replace_val
    if dtype == float and np.isnan(val) == True:
        return replace_val
    if dtype == int and np.isnan(val) == True:
        return replace_val
    return val


def add_detmap_info(aman, detmap_filename): 
    """Add detector mapping info into aman.det_info in the format that will be 
    generally available once this is done through Context
    
    Arguments
    ---------
    aman: AxisManager
    detmap_filename: path to file for detmap information. Does just blindly
        assume you are loading the correct file (sorry).
    """
    detmap = np.genfromtxt(detmap_filename, delimiter=',', skip_header=1,
                           dtype=[('smurf_band', '<f8'), ('res_index', '<f8'), ('freq_mhz', '<f8'), ('is_north', '<f8'), 
                                  ('is_highband', '<f8'), ('smurf_channel', '<f8'), ('smurf_subband', '<f8'), 
                                  ('bond_pad', '<f8'), ('mux_band', '<f8'), ('mux_channel', '<f8'), ('mux_subband', '<f8'),
                                  ('mux_layout_position', '<f8'), ('design_freq_mhz', '<f8'), ('bias_line', '<f8'),
                                  ('pol', '<U4'), ('bandpass', '<U4'), ('det_row', '<f8'), ('det_col', '<f8'), 
                                  ('pixel_num', '<f8'), ('pixel_num_pin_skip', '<f8'), ('rhomb', '<f8'), 
                                  ('is_optical', '<f8'), ('det_x', '<f8'), ('det_y', '<f8'), ('angle_raw_deg', '<f8'), 
                                  ('angle_actual_deg', '<f8'), ('det_type', '<U4'), ('detector_id', '<U50'), ('flags', '<f8'), 
                                  ('fit_fr_mhz', '<f8'), ('fit_q', '<f8'), ('fit_qe_real', '<f8'), ('fit_qe_imag', '<f8'), 
                                  ('fit_delay_ns', '<f8'), ('fit_phi_rad', '<f8'), ('fit_fmin_mhz', '<f8'),
                                  ('fit_amag', '<f8'), ('fit_aslope', '<f8')])
    

    if "det_id" in aman:
        print("det_id key already in AxisManager, have you already run this function?")
        return
    aman.det_info.wrap_new("det_id", ("dets",), dtype='<U50')
    
    wafer = core.AxisManager( aman.dets )
    wafer.wrap_new( "pol", ("dets",), dtype="U4")
    wafer.wrap_new( "det_x", ("dets",), dtype=float)
    wafer.wrap_new( "det_y", ("dets",), dtype=float)
    wafer.wrap_new( "angle", ("dets",), dtype=float)
    wafer.wrap_new( "det_row", ("dets",), dtype=int)
    wafer.wrap_new( "det_col", ("dets",), dtype=int)
    wafer.wrap_new( "type", ("dets",), dtype="U4")
    wafer.wrap_new( "bandpass", ("dets",), dtype="U4")

    for i in range(aman.dets.count):
        msk = np.all( [aman.det_info.smurf.band[i] == detmap["smurf_band"],
                       aman.det_info.smurf.channel[i] == detmap["smurf_channel"],], axis=0)
        if not np.sum(msk)==1:
            ## probably fine
            continue

        aman.det_info.det_id[i] = detmap["detector_id"][msk][0]
        
        wafer["pol"][i] = replace_none(detmap["pol"][msk][0], str, "NC")
        wafer["det_x"][i] = replace_none(detmap["det_x"][msk][0], float, np.nan)
        wafer["det_y"][i] = replace_none(detmap["det_y"][msk][0], float, np.nan)
        wafer["angle"][i] = replace_none(np.radians(detmap["angle_actual_deg"][msk][0]), float, np.nan)
        wafer["det_row"][i] = replace_none(detmap["det_row"][msk][0], int, -1)
        wafer["det_col"][i] = replace_none(detmap["det_col"][msk][0], int, -1)
        wafer["type"][i] = replace_none(detmap["det_type"][msk][0], str, "NC")
        bandpass = replace_none(detmap["bandpass"][msk][0], str, "NC")
        if not bandpass == "NC":
            bandpass = f"f{bandpass}"
        wafer["bandpass"][i] = bandpass
        
    aman.det_info.wrap("wafer", wafer)


def load_hwp_data(aman, configs=None, data_dir=None):
    """Load HWP data that will match with aman timestamps and
    interpolate angles into hwp_angle

    Arguments
    ----------
    aman : AxisManager
        AxisManager of loaded SMuRF data
    configs : (optional) config filename or dictionary containing "hwp_prefix"
    data_dir : (optional) the "hwp_prefix" data directory. overrides configs

    Wraps HWP data into aman.hwp_angle
    """
    if "hwp_angle" in aman:
        raise ValueError("hwp_angle already exists in aman")

    if configs is None and data_dir is None:
        raise ValueError("Must pass config or data_dir")
    if data_dir is None:
        if type(configs) == str:
            configs = yaml.safe_load(open(configs, "r"))
        data_dir = configs["hwp_prefix"]

    data = load_range(
        float(aman.timestamps[0]-5), float(aman.timestamps[-1]+5),
        fields=["hwp.hwp_angle"], data_dir=data_dir
    )
    time = data["hwp.hwp_angle"][0]
    if len(time) == 0:
        raise ValueError("No HWP data found that overlaps aman")
    if time[0] > aman.timestamps[0] or time[-1] < aman.timestamps[-1]:
        logger.warning("HWP data does not cover all of AxisManager, " +
                       "extrapolations may be unstable")

    hwp_uw = np.unwrap(data["hwp.hwp_angle"][1])
    hwp = interp1d(data["hwp.hwp_angle"][0], hwp_uw, bounds_error=False,
                   fill_value="extrapolate")
    aman.wrap("hwp_angle", np.mod(hwp(aman.timestamps), 2*np.pi),
              [(0, "samps")])
