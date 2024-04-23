import os
import yaml
import argparse
import logging
from typing import Optional

from sotodlib import core
from sotodlib.io import hk_utils
from sotodlib.site_pipeline import util
logger = util.init_logger('hk2meta', 'hk2meta: ')

def get_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()
    parser.add_argument(
        'context',
        help="Path to context yaml file")
    parser.add_argument(
        'config',
        help="configuration yaml file.")
    parser.add_argument(
        '-o', '--output_dir', action='store', default=None, type=str,
        help='output data directory, overwrite config output_dir')
    parser.add_argument(
        '--verbose', default=2, type=int,
        help="increase output verbosity. \
        0: Error, 1: Warning, 2: Info(default), 3: Debug")
    parser.add_argument(
        '--overwrite',
        help="If true, overwrites existing entries in the database",
        action='store_true',
    )
    parser.add_argument(
        '--query_text', type=str,
        help="Query text",
    )
    parser.add_argument(
        '--query_tags', nargs="*", type=str,
        help="Query tags",
    )
    parser.add_argument(
        '--min_ctime', type=int,
        help="Minimum timestamp for the beginning of an observation list",
    )
    parser.add_argument(
        '--max_ctime', type=int,
        help="Maximum timestamp for the beginning of an observation list",
    )
    parser.add_argument(
        '--obs_id', type=str,
        help="obs_id of particular observation if we want to run on just one",
    )
    return parser
    
def main(context: str,
        config: str,
        output_dir: Optional[str] = None,
        verbose: Optional[int] = 2,
        overwrite: Optional[bool] = False,
        query_text: Optional[str] = None,
        query_tags: Optional[list] = None,
        min_ctime: Optional[float] = None,
        max_ctime: Optional[float] = None,
        obs_id: Optional[str] = None,
        ):
    # Set verbose
    if verbose == 0:
        logger.setLevel(logging.ERROR)
    elif verbose == 1:
        logger.setLevel(logging.WARNING)
    elif verbose == 2:
        logger.setLevel(logging.INFO)
    elif verbose == 3:
        logger.setLevel(logging.DEBUG)
    
    logger.info(f'min_ctime: {min_ctime}')
    # load context
    ctx = core.Context(context)
    
    # load configuration file
    with open(config) as f:
        hk2meta_config = yaml.safe_load(f)
    
    if output_dir is None:
        if 'output_dir' in hk2meta_config.keys():
            output_dir = hk2meta_config['output_dir']
        else:
            raise ValueError('output_dir is not specified.')
    if query_text is None:
        if 'query_text' in hk2meta_config.keys():
            query_text = hk2meta_config['query_text']
    if query_tags is None:
        if 'query_tags' in hk2meta_config.keys():
            query_tags = hk2meta_config['query_tags']
    if min_ctime is None:
        if 'min_ctime' in hk2meta_config.keys():
            min_ctime = hk2meta_config['min_ctime']
    if max_ctime is None:
        if 'max_ctime' in hk2meta_config.keys():
            max_ctime = hk2meta_config['max_ctime']
    
    # Load metadata sqlite
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    output_prefix = hk2meta_config['output_prefix']
    man_db_filename = os.path.join(output_dir, f'{output_prefix}.sqlite')
    if os.path.exists(man_db_filename):
        logger.info(f"Mapping {man_db_filename} for the \
                    archive index.")
        man_db = core.metadata.ManifestDb(man_db_filename)
    else:
        logger.info(f"Creating {man_db_filename} for the \
                     archive index.")
        scheme = core.metadata.ManifestScheme()
        scheme.add_exact_match('obs:obs_id')
        scheme.add_data_field('dataset')
        man_db = core.metadata.ManifestDb(
            man_db_filename,
            scheme=scheme
        )
    
    # query observations
    if obs_id is not None:
        tot_query = f"obs_id=='{obs_id}'"
    else:
        tot_query = "and "
        if query_text is not None:
            tot_query += f"{query_text} and "
        if min_ctime is not None:
            tot_query += f"timestamp>={min_ctime} and "
        if max_ctime is not None:
            tot_query += f"timestamp<={max_ctime} and "
        tot_query = tot_query[4:-4]
        if tot_query == "":
            tot_query = "1"
    
    logger.info(f'tot_query: {tot_query}')
    obs_list= ctx.obsdb.query(tot_query, query_tags)
    
    # make obs_id
    for obs in obs_list:
        obs_id = obs['obs_id']
        try:
            meta = ctx.get_meta(obs_id)
            aman = ctx.get_obs(obs_id, dets=[])
            
            
            
            _hkman = hk_utils.get_detcosamp_hkaman(aman, 
                                      fields = hk2meta_config['fields'],
                                      data_dir = hk2meta_config['input_dir'])
            
            dt_samp_hk = hk2meta_config['dt_samp_hk']
            start = float(aman.timestamps[0] - 3*dt_samp_hk)
            stop = float(aman.timestamps[-1] + 3*dt_samp_hk)
            _data = hk_utils.sort_hkdata(start=start, stop=stop, fields=hk2meta_config['fields'],
                                         data_dir=hk2meta_config['input_dir'], alias=None)
            _hkman = hk_utils.make_hkaman(grouped_data=_data, alias_exists=False,
                                          det_cosampled=True, det_aman=aman)
            
            hkman = core.AxisManager(meta.dets, aman.samps)
            hkman.wrap('timestamps', aman.timestamps, [(0, 'samps')])

            full_fields = hk2meta_config['fields']
            aliases = hk2meta_config['aliases']
            data_fields = [full_field.split('.')[1] for full_field in full_fields]
            num_different_field = 0
            for i, (full_field, data_field, alias) in enumerate(zip(full_fields, data_fields, aliases)):    
                if i > 0:
                    num_different_field += int(data_fields[i-1] != data_field)
                i_in_same_field = i - num_different_field
                hkman.wrap(alias, _hkman[data_field][data_field][i_in_same_field], [(0, 'samps')])
            
            h5_filename = f"{output_prefix}_{obs_id.split('_')[1][:4]}.h5"
            output_filename = os.path.join(output_dir, h5_filename)
            hkman.save(dest=output_filename, group=obs_id, overwrite=overwrite, compression='gzip')
            man_db.add_entry({'obs:obs_id': obs_id, 'dataset': obs_id}, 
                     filename=output_filename, replace=overwrite)
            logger.info(f"saved: {obs_id}")
            
        except Exception as e:
            logger.error(f"Exception '{e}' thrown while processing {obs_id}")
            continue

if __name__ == '__main__':
    parser = get_parser(parser=None)
    args = parser.parse_args()
    main(**vars(args))
