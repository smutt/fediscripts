#!/usr/bin/env python3

# Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import argparse
import json
import os
import sys

class TLDCount(): # Can't use a simple dict() because we need to sort by count
  def __init__(self, tld, count):
    self.tld = str(tld)
    self.count = int(count)

  def __repr__(self):
    return self.tld + ":" + str(self.count)

  def __str__(self):
    return self.__repr__()

  def to_json(self):
    return '\"' + self.tld + '\": ' + str(self.count)


# BEGIN EXECUTION
ap = argparse.ArgumentParser(description='Count TLDs used from a consolidated file')
ap.add_argument('-c', '--categorize', dest='cat', nargs=1, help='Categorize by supplied CSV file')
ap.add_argument('-i', '--input-file', dest='infile', type=str, help='Input file')
ap.add_argument('-j', '--json', dest='json', action='store_true', default=False, help='Output JSON')
ap.add_argument('-x', '--exclude', dest='exclude', nargs='+', help='If categorizing, exclude these TLDs from categorization')
args = ap.parse_args()

if not os.path.exists(args.infile):
  print("Error: Input file does not exist:" + args.infile)
  exit(1)

if not os.access(args.infile, os.R_OK):
  print("Error: Input file not readable:" + args.infile)
  exit(1)

if args.exclude and not args.cat:
  print("--exclude requires --categorize be present")
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

  if args.exclude:
    for tld in args.exclude:
      categories[tld] = tld

  output = {}
  for tld,count in tlds.items():
    if categories[tld] in output:
      output[categories[tld]] += count
    else:
      output[categories[tld]] = count

  if args.json:
    print(json.dumps(output))
  else:
    for category,count in output.items():
      print(category + ":" + str(count))

else:
  output = [TLDCount(k, v) for k,v in tlds.items()]
  output.sort(key=lambda x: x.count, reverse=True)
  if args.json:
    ss = '{'
    for tt in output:
      ss += tt.to_json() + ','
    print(ss.rstrip(',') + '}')
  else:
    for tt in output:
      print(repr(tt))
