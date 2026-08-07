# standard imports
from dataclasses import dataclass
import logging
import sys
import time


@dataclass
class FinneyBlockData:
    block: int | None
    time: int


def format_time(total_time):
    m = total_time/60
    minutes = int(m)
    seconds = round((m - minutes)*60)

    runtime_text = [f"{minutes} minutes"] if minutes else []
    if seconds:
        runtime_text += [f"{seconds} seconds"]
    runtime_text = ", ".join(runtime_text)

    return runtime_text


def _get_logger():

    class BtDateFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            created = self.converter(record.created)
            if datefmt:
                s = time.strftime(datefmt, created)
            else:
                s = time.strftime("%Y-%m-%d %H:%M:%S", created)
            s += f".{int(record.msecs):03d}"
            return s

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(BtDateFormatter("%(asctime)s | %(levelname)s | %(message)s"))

    logger = logging.getLogger("bittensor")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    return logger


logger = _get_logger()
