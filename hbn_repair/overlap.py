"""A10: compare embedded and separate task signals without changing either file"""

import struct

import numpy as np
from scipy.io.matlab._mio5 import MatFile5Reader

from .events import STARTS, read_header


# movie starts at sample 100 in left and 0 in right -> compare the following shared samples
def compare_signals(left, right, code):
    """compare the shared task interval -> 'matches', 'differs' or 'unknown'"""
    left_header, right_header = read_header(left), read_header(right)
    if (left_header["srate"] != right_header["srate"] or
            left_header["channel_names"] != right_header["channel_names"] or
            not left_header["channel_names"] or
            left_header["trials"] != 1 or right_header["trials"] != 1):
        return "unknown"

    intervals = [task_interval(header, code) for header in (left_header, right_header)]
    if None in intervals:
        return "unknown"

    (left_start, left_end), (right_start, right_end) = intervals
    samples = min(left_end - left_start, right_end - right_start)
    if samples < 32:
        return "unknown"

    left_data, right_data = signal_array(left), signal_array(right)
    if left_data.shape[0] != right_data.shape[0]:
        return "unknown"

    # compare every channel and sample, keeping memory bounded for long movies
    for start in range(0, samples, 32_768):
        end = min(start + 32_768, samples)
        if not np.array_equal(left_data[:, left_start + start:left_start + end],
                              right_data[:, right_start + start:right_start + end], equal_nan=True):
            return "differs"

    return "matches"


# a unique movie marker at latency 101, then another task at 501 -> samples [100, 500)
def task_interval(header, code):
    markers = [(str(event["event_code"]).strip(), float(event["latency"]) - 1)
               for event in header["events"]]
    starts = [sample for marker, sample in markers if marker == code]
    if len(starts) != 1 or not starts[0].is_integer():
        return None

    start = int(starts[0])
    end = min([sample for marker, sample in markers if marker in STARTS and sample > start]
              + [header["pnts"]])
    if not float(end).is_integer() or not 0 <= start < end <= header["pnts"]:
        return None

    return start, int(end)


# R1–R11 store uncompressed float arrays as top-level MATLAB 'data'; map them read-only
def signal_array(path):
    with path.open("rb") as stream:
        reader = MatFile5Reader(stream)
        reader.initialize_read()
        reader.read_file_header()

        while True:
            header, end = reader.read_var_header()
            if header.name == b"data":
                kind, length = struct.unpack("<II", stream.read(8))
                dtype = {7: np.dtype("<f4"), 9: np.dtype("<f8")}[kind]
                assert length == int(np.prod(header.dims)) * dtype.itemsize
                return np.memmap(path, dtype=dtype, mode="r", offset=stream.tell(),
                                 shape=tuple(header.dims), order="F")

            stream.seek(end)
