#!/usr/bin/env python3



import os.path
import logging
import argparse

import ncheck

RMAP = {"OK": {"code": 0},
        "WARNING": {"code": 1},
        "CRITICAL": {"code": 2},
        "UNKNOWN": {"code": 3}}

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument("-v", "--verbose", action="append_const", help="Verbosity Controls",
                        const=1, default=[])
    parser.add_argument("-l", "--delivered_loc", default=os.environ.get("DELIVERED_LOC", "/var/spool/nagios/delivered"))
    parser.add_argument("-3", "--s3", default=False, action="store_true", help="Look in S3 instead of local FS.")
    parser.add_argument("-b", "--bucket", default=None, type=str, help="S3 Bucket to Reach Out to")
    parser.add_argument("-p", "--aws_profile", default=None, type=str, help="AWS Profile to Use (default default).")
    parser.add_argument("-m", "--fresh", default=60, type=int)
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

    this_check_kwargs = dict(fresh=args.fresh)

    # Build File URI Find File
    if args.s3 is False:
        # Local File
        file_uri = os.path.join(args.delivered_loc, "{}.{}.json".format(args.host, args.check))
    else:
        # S3
        file_uri = "s3://{}/{}".format(args.bucket, "{}/{}.json".format(args.host, args.check))

        this_check_kwargs["profile"] == args.aws_profile

    this_check = ncheck.NCheck(uri=file_uri, **this_check_kwargs)

    this_check.do_response()



