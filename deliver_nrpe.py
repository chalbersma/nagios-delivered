#!/usr/bin/env python3

"""
Requires nagios-nrpe-plugin
"""


import subprocess
import argparse
import logging
import os.path
import os
import configparser
import itertools
import re
import ncheck


DEFAULT_NRPE = "/etc/nagios/nrpe.cfg"
CHECK_NRPE = "/usr/lib/nagios/plugins/check_nrpe"

RMAP = {"OK": {"code": 0},
        "WARNING": {"code": 1},
        "CRITICAL": {"code": 2},
        "UNKNOWN": {"code": 3}}

def read_nrpe_configuration(config_file=DEFAULT_NRPE, running_configuration={}, **kwargs):

    config = configparser.ConfigParser(interpolation=None)
    logger = logging.getLogger("read_nrpe_configuration")

    with open(args.nrped) as nrpe_cfg_fobj:
        config.read_file(itertools.chain(["[nrpe]"], nrpe_cfg_fobj), source=config_file)

    new_items = config._sections["nrpe"]

    logger.debug(new_items)


    delivery_path = kwargs.get("delivery_path", new_items.get("delivery_path", None))
    delivery_profile = kwargs.get("delivery_profile", new_items.get("delivery_profile", None))

    logger.debug(delivery_path, delivery_profile)


    for k, v in running_configuration.items():
        if k == "include":
            # Include Single File
            logger.debug("Processing File : {}".format(v))
            new_items, x, y = read_nrpe_configuration(config_file=v,
                                                running_configuration=new_items)
        elif k == "include_dir":
            # Walk Dir and Include Files
            for (dirpath, dirnames, filenames) in os.walk(v):
                for singlefile in filenames:
                    this_file = dirpath + "/" + singlefile
                    new_items, x, y = read_nrpe_configuration(config_file=this_file,
                                                        running_configuration=new_items)

    return {**new_items, **running_configuration}, delivery_path, delivery_profile

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument("-v", "--verbose", action="append_const", help="Verbosity Controls",
                        const=1, default=[])
    parser.add_argument("-n", "--nrped", type=str, help="Location of NRPED Config", default=DEFAULT_NRPE)
    parser.add_argument("-H", "--overridehost", help="Override Host Name", default="host")
    parser.add_argument("-b", "--bin", help="Check NRPE Binary", default=CHECK_NRPE)
    parser.add_argument("-c", "--check", help="Run this Specific Check", default=False)
    parser.add_argument("-d", "--delivery_path", help="Directory/Bucket to Deliver Checks too", default=None)
    parser.add_argument("-p", "--aws_profile", help="If delivery to AWS which profile to use", default=None)
    parser.add_argument("-C", "--confirm", help="Confirm desire to store", default=False, action="store_true")

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
    elif VERBOSE >= 4:
        logging.basicConfig(level=logging.DEBUG)
        extra_level = logging.DEBUG

    for mod in EXTRA_MODULES:
        logging.getLogger(mod).setLevel(extra_level)

    logger = logging.getLogger("check_delivered.py")

    logger.error("tst")

    if args.check is not False:
        process_checks = [args.check]
    else:
        # Process Nagios for Checks

        running_config, delivery_path, delivery_profile = read_nrpe_configuration(config_file=args.nrped, running_configuration={})

        if args.delivery_path != None:
            delivery_path = args.delivery_path
        elif args.aws_profile != None:
            delivery_profile = args.aws_profile

        logger.debug(running_config)
        logger.debug("Delivery Settings: {}, {}, {}".format(args.confirm, delivery_path, delivery_profile))

        all_checks = []

        for k, v in running_config.items():
            match = re.search("command\[(.+)\]", k)

            if match is not None:
                check_name = match.group(1)
                logger.debug("Found Check Named {} : {}".format(check_name, v))

                try:
                    run = subprocess.run(v, shell="/bin/bash", capture_output=True)
                except Exception as run_error:
                    logger.error("Unable to Run Check {}".format(v))
                else:
                    this_response = {"code" : int(run.returncode), "string": run.stdout.decode()}
                    logger.debug(this_response)

                    this_nrpe = ncheck.NCheck(response=this_response, check=check_name,
                                              profile=delivery_profile,
                                              path=delivery_path,
                                              do_storage=args.confirm)
