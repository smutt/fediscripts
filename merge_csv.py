#!/usr/bin/env python3

#  Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>
# Merge 2 CSV files and print some stats in the process

import argparse
import fediserver

# BEGIN EXECUTION
ap = argparse.ArgumentParser(description='Merge 2 CSV files and print some stats in the process')
ap.add_argument('-i', '--input-file', nargs=2, dest='infile', type=str, help='2 input files.')
ap.add_argument('-o', '--output-file', dest='outfile', type=str, help='Consolidated output file to update, overrides stdout')
args = ap.parse_args()

if not args.infile:
  print('No input')
  exit(1)

if len(args.infile) != 2:
  print('Require 2 input files')
  exit(1)

f0 = fediserver.parse_consolidated(args.infile[0])
f1 = fediserver.parse_consolidated(args.infile[1])

not_in_f0 = not_in_f1 = 0
for k,v in f0.items():
  if k not in f1:
    not_in_f1 += 1

for k,v in f1.items():
  if k not in f0:
    not_in_f0 += 1
    f0[k] = v

print(str(not_in_f0) + ' instances not in ' + args.infile[0])
print(str(not_in_f1) + ' instances not in ' + args.infile[1])

if not args.outfile:
  print('Not merging, no output file')
else:
  fediserver.write_consolidated(args.outfile, f0)
