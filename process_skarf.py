#!/usr/bin/env python3

#  Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import sys
import argparse
import urllib.parse

class FediServer():
  def __init__(self, domain, ts):
    self.domain = domain
    self.first_seen = ts
    self.last_seen = ts
    self.hits = 1

  def __repr__(self):
    return "dn: " + self.domain + " hits:" + str(self.hits) + " fs:" + str(self.first_seen) + " ls:" + str(self.last_seen)

  def __str__(self):
    return self.__repr__()

  def push(self, ts):
    self.hits += 1
    if ts < self.first_seen:
      self.first_seen = ts
    if ts > self.last_seen:
      self.last_seen = ts


# BEGIN EXECUTION
ap = argparse.ArgumentParser(description='Parse domain names from input')
ap.add_argument(nargs='?', metavar='file', dest='infile', type=argparse.FileType('r'),
                  default=sys.stdin, help='Input file if not using stdin')
ap.add_argument('-d', '--delimiter', type=str, default=',', dest='delimiter', help='Input delimiter')
ap.add_argument('-t', '--top', dest='top', type=int, help='Output sorted top talking domains only')
args = ap.parse_args()

fedi_servers = {}
for line in args.infile.read().split('\n'):
  if len(line) > 0:
    toks = line.split(args.delimiter)

    try:
      ts = int(toks[0])
    except: # invalid timestamp
      continue

    for tok in toks[1:]:
      try:
        url = urllib.parse.urlparse(tok)
      except ValueError:
        continue

      if url.hostname:
        if url.hostname in fedi_servers:
          fedi_servers[url.hostname].push(ts)
        else:
          fedi_servers[url.hostname] = FediServer(url.hostname, ts)

if args.top:
  servers = [v for k,v in fedi_servers.items()]
  servers.sort(key=lambda x: x.hits, reverse=True)
  for ii in range(args.top):
    if ii < len(servers):
      print(servers[ii])
else:
  for key, server in fedi_servers.items():
    print(server)
