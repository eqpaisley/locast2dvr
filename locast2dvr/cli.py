#!/usr/bin/env python3

import logging

import click
import click_config_file
from click_option_group import MutuallyExclusiveOptionGroup, optgroup

from .utils import Configuration

logger = logging.getLogger("CLI")


@click.command(context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True,
))
@click.option('-U', '--username', required=True, type=click.STRING, help='Locast username', metavar='USERNAME')
@click.password_option('-P', '--password', required=True, help='Locast password', metavar='PASSWORD')
@click.option('-u', '--uid', type=click.STRING, help='Unique identifier of the device', metavar='UID', required=True)
@click.option('-b', '--bind', 'bind_address', default="127.0.0.1", show_default=True, help='Bind IP address', metavar='IP_ADDR', )
@click.option('-p', '--port', default=6077, show_default=True, help='Bind tcp port', metavar='PORT')
@click.option('-f', '--ffmpeg', help='Path to ffmpeg binary', metavar='PATH', default='ffmpeg', show_default=True)
@click.option('-v', '--verbose', count=True, help='Enable verbose logging')
@optgroup.group('\nMultiplexing')
@optgroup.option('-M', '--multiplex-debug', is_flag=True, help='Multiplex devices AND start individual instances (multiplexer is started on the last port + 1)')
@optgroup.option('-m', '--multiplex', is_flag=True, help='Multiplex devices')
@optgroup.group('\nLocation overrides', cls=MutuallyExclusiveOptionGroup)
@optgroup.option('--override-location', type=str, help='Override location', metavar="LAT,LONG")
@optgroup.option('--override-zipcodes', type=str, help='Override zipcodes', metavar='ZIP')
@optgroup.group('\nDebug options')
@optgroup.option('--bytes-per-read', type=int, default=1152000, show_default=True, help='Bytes per read', metavar='BYTES')
@optgroup.option('--tuner-count', default=3, show_default=True, help='Tuner count', metavar='COUNT')
@optgroup.option('--device-model', default='HDHR3-US', show_default=True, help='HDHomerun device model reported to clients')
@optgroup.option('--device-firmware', default='hdhomerun3_atsc', show_default=True, help='Model firmware reported to clients')
@optgroup.option('--device-version', default='1.2.3456', show_default=True, help='Model version reported to clients')
@click_config_file.configuration_option()
def cli(*args, **config):
    """Locast to DVR (like Plex or Emby) integration server"""
    config = Configuration(config)
    log_level = logging.DEBUG if config.verbose >= 2 else logging.INFO
    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s: %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S', level=log_level)

    # We only import main after the configuration is valid and logging is set,
    # since loading Main will load a bunch of other stuff
    from .main import Main
    Main(config).start()
