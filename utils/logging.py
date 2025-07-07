"""
Logging
------------

Logging tools with cpymad perks.
"""
import logging
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from contextlib import contextmanager

LOG_OUT_LVL = logging.DEBUG - 1
LOG_CMD_LVL = logging.DEBUG - 2

# ASCII Colors, change to your liking (the last three three-digits are RGB)
# Default colors should be readable on dark and light backgrounds
COLORS = dict(
    reset='\33[0m',
    name='\33[0m\33[38;2;127;127;127m',
    msg='',
    cmd_name='\33[0m\33[38;2;132;168;91m',
    cmd_msg='',
    out_name='\33[0m\33[38;2;114;147;203m',
    out_msg='\33[0m\33[38;2;127;127;127m',
    warn_name='',
    warn_msg='\33[0m\33[38;2;193;134;22m',
)


class StreamToLogger(object):
    """ File-like stream object that redirects writes to a logger instance. """
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''

    def write(self, buf):
        last_line_empty = False
        for line in buf.rstrip().splitlines():
            try:
                line = line.decode('utf-8')  # convert madx output from binary
            except AttributeError:
                pass
            line = line.rstrip()

            if last_line_empty or len(line):
                self.logger.log(self.log_level, line)
                last_line_empty = False
            else:
                last_line_empty = True  # skips multiple empty lines

    def __call__(self, *args, **kwargs):
        self.write(*args, **kwargs)

    def flush(self):
        for handler in self.logger.handlers:
            handler.flush()


class LevelFilter(logging.Filter):
    """ To get messages only up to a certain level """
    def __init__(self, *levels):
        super(LevelFilter, self).__init__()
        self.__levels = levels

    def filter(self, log_record):
        return log_record.levelno in self.__levels


def _lvl_fmt(name_color='', msg_color=''):
    """ Defines the level/message formatter with colors """
    name_reset, msg_reset = '', ''
    if name_color:
        name_reset = COLORS['reset']
    if msg_color:
        msg_reset = COLORS['reset']

    return logging.Formatter(
        f'{name_color}%(levelname)7s{name_reset}'
        f' | '
        f'{msg_color}%(message)s{msg_reset}'
    )

def init_logging():
    """ Set up a basic logger. """
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.DEBUG if sys.flags.debug else logging.INFO,
        format= _lvl_fmt()._fmt,
        datefmt='%H:%M:%S',
    )


@contextmanager
def disable_logging(remaining_level: int = logging.WARNING):
    """ Temporarily disable logging up to the given level (excluding). """
    logging.disable(remaining_level-1)
    try:
        yield
    finally:
        logging.disable(logging.NOTSET)


def init_cpymad_logging(
        console: bool = True,
        command_log: Path = Path('madx_commands.madx'),
        output_log: Path = Path('madx_output.log'),
        colors: bool = True,
):
    """ Initialize a special logger for the cpymad output.
    These loggers are converted to file-like objects to which cpymad can "write".

    Args:
        console: Bool whether to add handlers to add output to the console
        output_log: Path to write madx-output to (None to deactivate)
        command_log: Path to write madx-commands to (None to deactivate)
        colors: Bool whether ascii-colors should be used

    Returns
        dict with StreamToLoggers 'stdout' and 'command_log'.
        Can be used as `Madx(**init_cpymad_logging())`
    """
    cdict = defaultdict(str)
    if colors:
        cdict.update(COLORS)

    msg_fmt = logging.Formatter('%(message)s')

    if LOG_CMD_LVL > LOG_OUT_LVL:
        raise ValueError('Level for MAD-X commands need to be lower than for output')

    logging.addLevelName(LOG_OUT_LVL, 'madx')
    logging.addLevelName(LOG_CMD_LVL, 'cmd')

    # Get Logger
    cpymad_logger = logging.getLogger("cpymad")
    cpymad_logger.setLevel(LOG_CMD_LVL)
    cpymad_logger.propagate = False  # don't propagate to root logger

    # create logger for madx output
    if console:
        outstream_handler = logging.StreamHandler(sys.stdout)
        outstream_handler.setLevel(LOG_OUT_LVL)
        outstream_handler.addFilter(LevelFilter(LOG_OUT_LVL))
        outstream_handler.setFormatter(_lvl_fmt(cdict['out_name'], cdict['out_msg']))
        cpymad_logger.addHandler(outstream_handler)

    if output_log is not None:
        outfile_handler = logging.FileHandler(output_log, mode='w')
        outfile_handler.setFormatter(msg_fmt)
        outfile_handler.addFilter(LevelFilter(LOG_OUT_LVL, LOG_CMD_LVL))
        cpymad_logger.addHandler(outfile_handler)
    out_stream = StreamToLogger(cpymad_logger, log_level=LOG_OUT_LVL)

    # create logger for madx commands
    if console:
        cmdstream_handler = logging.StreamHandler(sys.stdout)
        cmdstream_handler.setLevel(LOG_CMD_LVL)
        cmdstream_handler.addFilter(LevelFilter(LOG_CMD_LVL))
        cmdstream_handler.setFormatter(_lvl_fmt(cdict['cmd_name'], cdict['cmd_msg']))
        cpymad_logger.addHandler(cmdstream_handler)

    if command_log is not None:
        cmdfile_handler = logging.FileHandler(command_log, mode='w')
        cmdfile_handler.addFilter(LevelFilter(LOG_CMD_LVL))
        cmdfile_handler.setFormatter(msg_fmt)
        cpymad_logger.addHandler(cmdfile_handler)
    cmd_stream = StreamToLogger(cpymad_logger, log_level=LOG_CMD_LVL)

    return dict(stdout=out_stream, command_log=cmd_stream, stderr=subprocess.STDOUT)