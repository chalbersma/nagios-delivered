#!/usr/bin/env python3

import logging
import json
import time
import sys
import urllib.parse
import os.path
import io
import re
import platform
import socket

import boto3
import botocore.exceptions


class NCheck:
    '''
    Handles the Logic Around Nagios Checks, Ideally will Handle simple reading/writing of
    checks.
    '''

    _fresh_min = 60
    _RMAP = RMAP = {"OK": {"code": 0},
                    "WARNING": {"code": 1},
                    "CRITICAL": {"code": 2},
                    "UNKNOWN": {"code": 3}}

    _r_main = r".+(OK|WARNING|CRITICAL|UNKNOWN)[:\-\s]+(.+)"
    _r_perf = r"([\'\w+ ]+)=(\d+\.\d+|\d+)(;[\d\.]+;[\d\.]+;[\d\.]+)?"

    def __init__(self, **kwargs):

        self.logger = logging.getLogger("NCheck")

        self.kwargs = kwargs

        self.fresh = self.kwargs.get("fresh", self._fresh_min)
        self.RMAP = self.kwargs.get("rmap_override", self._RMAP)
        self.r_main = self.kwargs.get("r_main", self._r_main)
        self.r_perf = self.kwargs.get("r_perf", self._r_perf)
        self.hostname = self.kwargs.get("hostname", socket.getfqdn())
        self.checkname = self.kwargs.get("check", None)
        self.do_storage = self.kwargs.get("do_storage", False)

        self.path = self.kwargs.get("path", "/tmp/")

        # Handle File if data not explicitly given
        if "uri" in self.kwargs.keys() and "data" not in self.kwargs.keys():
            self.uri = urllib.parse.urlparse(self.kwargs["uri"])
            self.uri_args = urllib.parse.parse_qs(self.uri.query)

            self.logger.debug(self.uri)

            # Get the Data from this, Process it below.
            self.kwargs["data"] = self.grab_data_from_uri()

        if "response" in self.kwargs.keys():
            self.response = self.kwargs["response"]
            # Save Response as Data
            self.data = self.process_response()
            self.logger.debug("Processed Data : {}".format(self.data))

        if "data" in self.kwargs.keys():
            self.data = self.kwargs["data"]
            self.process_data()

        if self.do_storage is True:
            self.store_to_file()

    def process_response(self):

        """
        Process the Response and Return it
        :return:
        """

        tdata = {"ts": int(time.time())}

        for k, v in self.RMAP.items():
            if v["code"] == self.response["code"]:
                tdata["response"] = k

        match_result = re.search(self.r_main, self.response["string"], re.I)

        if match_result is not None:
            # this_message_type = match_result.group(1)

            this_message_full = match_result.group(2)
        else:
            # Abnormal Message use the Whole String (Dupe OK/OK stuff)
            this_message_full = self.response["string"]

        # Process Message
        message_array = this_message_full.split("|")

        tdata["msg"] = message_array[0]
        tdata["perf"] = dict()

        if len(message_array) == 2:
            # I have Performance Data to Add
            for this_perf in re.findall(self.r_perf, message_array[1], re.I):

                self.logger.debug(this_perf)

                cleaned_name = this_perf[0].lstrip(" ")

                primary_stat = this_perf[1]

                tdata["perf"][cleaned_name] = {"stat": primary_stat}

                if len(this_perf) == 3:
                    threshold_data = this_perf[2]
                    tdata["perf"][cleaned_name]["thresholds"] = threshold_data

        self.logger.debug(tdata)

        return tdata

    def grab_data_from_uri(self):

        data = None

        if self.uri.scheme == "s3":
            if self.kwargs.get("s3_client", None) == None:
                self.kwargs["s3_client"] = self.aws_client(client_type="s3")


            with io.BytesIO() as s3_file:
                try:
                    self.kwargs["s3_client"].download_fileobj(self.uri.netloc,
                                                              self.uri.path.lstrip("/"),
                                                              s3_file)

                except botocore.exceptions.ClientError as ce:
                    if ce.response['Error']['Code'] == "404":
                        self.logger.info("File {} Doesn't exist".format(self.uri.geturl()))
                    else:
                        self.logger.error("Unexpected S3 Client Error: {}".format(ce))
                    data = {"ct": int(time.time()),
                            "result": "UNKNOWN",
                            "msg": "S3 Error : {}".format(ce)}
                else:
                    data = json.load(s3_file.read())

        elif self.uri.scheme in ("file", ""):
            local_file = self.uri.path
            if len(self.uri.netloc) >= 1 and self.uri.scheme == "file":
                # Relative Path
                local_file = os.path.expanduser("{}{}".format(self.uri.netloc, self.uri.path))

            with open(local_file, "r") as local_fobj:
                data = json.load(local_fobj)

        return data

    def aws_client(self, client_type="s3"):

        """
        Get me a Boto Client for given type
        :return:
        """

        try:
            if self.kwargs.get("aws_session", None) is None:
                self.kwargs["aws_session"] = boto3.session.Session(profile_name=self.kwargs.get("profile", None))

        except Exception as connection_error:
            self.logger.error("Unable to Connect to AWS Profile".format(self.kwargs.get("profile", "default")))
            raise connection_error
        else:
            self.logger.debug("Connected to Account : {}".format(
                self.kwargs["aws_session"].client('sts').get_caller_identity()["Account"]))

            this_client = self.kwargs["aws_session"].client(client_type)

        return this_client

    def process_data(self):

        '''
        Processes a Raw Dictionary of Check Data
        :return:
        '''

        # Check Timeout
        must_beat_ts = int(time.time()) - self.fresh * 60

        if self.data["ct"] < must_beat_ts:
            self.response["string"] = "UNKNOWN - Check Result Found but Stale"
        else:
            # Parse
            if self.data["result"] not in self.RMAP.keys():
                self.response["string"] = "UNKNOWN - Result {} Unknown".format(self.data["result"])
            else:
                self.response["code"] = self.RMAP[self.data["result"]]["code"]
                self.response["string"] = "{result} - {msg} ".format(**self.data)

            # Add perf Data
            perf_bits = ["{}={}{}".format(k, v["stat"], v.get("thresholds", "")) for k, v in
                         self.data.get("perf", dict()).items()]
            if len(perf_bits) > 0:
                self.response["string"] = "{}| {}".format(self.response["string"], " ".join(perf_bits))

    def store_to_file(self, path=None):

        '''
        Store to File (either Local or S3).

        :param path:
        :return:
        '''

        if self.checkname is None:
            raise ValueError("Specify a Checkname to use this functionality.")

        if self.path is None:
            self.logger.warning("No Path specified, no writing to be attempted")
            return

        if self.path.startswith("s3://"):
            s3 = True
            if self.kwargs.get("s3_client", None) is None:
                self.kwargs["s3_client"] = self.aws_client(client_type="s3")
        else:
            s3 = False

        # Build File URI Find File
        if s3 is False:
            # Local File
            filename = os.path.join(self.path, "{}.{}.json".format(self.hostname, self.checkname))

            with open(filename, "w") as write_fobj:
                json.dump(self.data, write_fobj, sort_keys=2, indent=2, default=str)

        else:
            parsed_s3_path = urllib.parse.urlparse(self.path)
            bucket = parsed_s3_path.netloc
            key = "{}/{}.json".format(self.hostname, self.checkname)

            self.kwargs["s3_client"].put_object(Body=json.dumps(self.data, sort_keys=2, indent=2, default=str),
                                                Bucket=bucket,
                                                Key=key)

    def do_response(self):

        """
        Actually Print and Exit Given the Data in the Response
        :return:
        """

        print(self.response["string"])

        sys.exit(self.response["code"])
