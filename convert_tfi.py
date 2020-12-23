#!/usr/bin/env python3

# Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>
# This script converts hosts gathered via the GraphQL interface of the-federation.info/graphql into our CSV format

# Generate hosts with this graphQL code:
'''
{ nodes{
  host
}
}
'''

import os
import argparse
import json
import time
import fediserver

# BEGIN EXECUTION
ap = argparse.ArgumentParser(description='Convert hosts from the-federation.info into our CSV format')
ap.add_argument('-i', '--input-file', dest='infile', type=str, help='Input file')
ap.add_argument('-o', '--output-file', dest='outfile', type=str, help='Consolidated output file to write')
args = ap.parse_args()

if not args.outfile:
  print("No output file")
  exit(1)

if not args.infile:
  print("No input file")
  exit(1)

if not os.path.exists(args.infile):
  print("Bad input")
  exit(1)

if not os.access(args.infile, os.R_OK):
  print("Bad input")
  exit(1)

fh = open(args.infile, 'r')
js = json.loads(fh.read())

instances = {}
for entry in js['data']['nodes']:
  if ':' in entry['host']: # We don't want special port numbers, prolly Matrix.org host, ignore
    continue

  instances[entry['host']] = fediserver.FediServer(entry['host'], int(time.time()), hits=0)

fediserver.write_consolidated(args.outfile, instances)
