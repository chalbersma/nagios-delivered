#!/usr/bin/env python3



import json
import os
import time
import os.path
import logging
import argparse
import sys

RMAP = {"OK": {"code": 0},
            "WARNING": {"code": 1},
            "CRITICAL": {"code": 2},
            "UNKNOWN": {"code": 3}}

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument("-v", "--verbose", action="append_const", help="Verbosity Controls",
                        const=1, default=[])
    parser.add_argument("-l", "--delivered_loc", default=os.environ.get("DELIVERED_LOC", "/var/spool/nagios/delivered"))
    parser.add_argument("-m", "--fresh", default=30, type=int)
    parser.add_argument("host", default="host")
    parser.add_argument("check", default="check")

    args = parser.parse_args()

    VERBOSE = len(args.verbose)

    EXTRA_MODULES = ["boto3"]
    extra_level = logging.ERROR

    if VERBOSE == 0:
        logging.basicConfig(level=logging.ERROR)
        extra_level = logging.ERROR
    elif VERBOSE == 1:
        logging.basicConfig(level=logging.WARNING)
        extra_level = logging.ERROR
    elif VERBOSE == 2:
        logging.basicConfig(level=logging.INFO)
        extra_level = logging.WARNING
    elif VERBOSE == 3:
        logging.basicConfig(level=logging.DEBUG)
        extra_level = logging.INFO
    elif VERBOSE > 4:
        logging.basicConfig(level=logging.DEBUG)
        extra_level = logging.DEBUG

    for mod in EXTRA_MODULES:
        logging.getLogger(mod).setLevel(extra_level)

    logger = logging.getLogger("check_delivered.py")

    # Find File
    check_file = os.path.join(args.delivered_loc, "{}.{}.json".format(args.host, args.check))

    response = {"string": "UNKNOWN - Error",
                "code": 3}

    if os.path.isfile(check_file) is False or os.access(check_file, os.R_OK) is False:
        # Return Error
        response["string"] = "UNKNOWN - No Host/Check Combination Found"
    else:
        # Have File can Read
        try:
            with open(check_file, "r") as check_fobj:
                data = json.load(check_fobj)

            # TODO add Json validator

        except Exception as read_error:
            # Unable to Read File
            response["string"] = "UNKNOWN - Check Result Found, but Mangled"
        else:
            # Check Timeout
            must_beat_ts = int(time.time()) - args.fresh * 60

            if data["ct"] < must_beat_ts:
                response["string"] = "UNKNOWN - Check Result Found but Stale"
            else:
                # Parse
                if data["result"] not in RMAP.keys():
                    response["string"] = "UNKNOWN - Result {} Unknown"
                else:
                    response["code"] = RMAP[data["result"]]["code"]
                    response["string"] = "{result} - {msg} ".format(**data)

                # Add perf Data
                perf_bits = ["{}={}".format(k, v) for k, v in data.get("perf", dict()).items()]
                if len(perf_bits) > 0:
                    response["string"] = "{}| {}".format(response["string"], ", ".join(perf_bits))

    # Response
    print(response["string"])

    sys.exit(response["code"])


