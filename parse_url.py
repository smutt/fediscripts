#!/usr/bin/env python3

#  Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import os
import sys
import argparse
import re
import urllib.parse

ap = argparse.ArgumentParser(description='Parse domain names from input')
ap.add_argument(nargs='+', metavar='file', dest='infile', type=argparse.FileType('r'),
                  default=sys.stdin, help='Input file if not using stdin')
ap.add_argument('-d', '--delimiter', type=str, default=',', dest='delimiter', help='Input delimiter')
args = ap.parse_args()

for f in args.infile:
  for line in f.read().split('\n'):
    if len(line) > 0:
      toks = line.split(args.delimiter)
      output = toks[0]

      for tok in toks[1:]:
        try:
          url = urllib.parse.urlparse(tok)
          if url.hostname:
            output = output + ',' + url.hostname
        except ValueError:
          continue

    if len(output.strip()) > 0 and ',' in output:
      print(output.strip())
