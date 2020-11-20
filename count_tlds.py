#!/usr/bin/env python3

# Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import sys
import os
import argparse

class TLDCount():
  def __init__(self, tld, count):
    self.tld = str(tld)
    self.count = int(count)

  def __repr__(self):
    return self.tld + ":" + str(self.count)

  def __str__(self):
    return self.__repr__()


# BEGIN EXECUTION
ap = argparse.ArgumentParser(description='Count TLDs used from a consolidated file')
ap.add_argument(dest='infile', type=str, help='Input file')
ap.add_argument('-c', '--categorize', dest='cat', nargs=1, help='Categorize by supplied CSV file')
args = ap.parse_args()

if not args.infile:
  print("No input")
  exit(1)

if not os.path.exists(args.infile):
  print("Error: Input file does not exist:" + args.infile)
  exit(1)

if not os.access(args.infile, os.R_OK):
  print("Error: Input file not readable:" + args.infile)
  exit(1)

tlds = {}
fh = open(args.infile, 'r')
for line in fh.read().split('\n'):
  if len(line) == 0:
    continue
  if line[0] == '#':
    continue

  toks = line.split(',')
  tld = toks[0].split('.')[-1]
  if tld in tlds:
    tlds[tld] += 1
  else:
    tlds[tld] = 1

if args.cat:
  categories = {}
  fh = open(args.cat[0], 'r')
  for line in fh.read().split('\n'):
    if len(line) == 0:
      continue
    if line[0] == '#':
      continue

    toks = line.split(',')
    categories[toks[0]] = toks[1]
  fh.close()

  output = {}
  for tld,count in tlds.items():
   if categories[tld] in output:
     output[categories[tld]] += 1
   else:
     output[categories[tld]] = 1

  for category,count in output.items():
    print(category + ":" + str(count))

else:
  output = [TLDCount(k, v) for k,v in tlds.items()]
  output.sort(key=lambda x: x.count, reverse=True)
  for tt in output:
    print(repr(tt))
