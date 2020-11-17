#!/usr/bin/env python3

#  Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import sys
import argparse
import urllib.parse

class FediServer():
  def __init__(self, domain, first_seen, last_seen=None):
    self.domain = domain
    self.hits = 1
    self.first_seen = first_seen
    if last_seen:
      self.last_seen = last_seen
    else:
      self.last_seen = first_seen

  def __repr__(self):
    return "dn: " + self.domain + " hits:" + str(self.hits) + " fs:" + str(self.first_seen) + " ls:" + str(self.last_seen)

  def __str__(self):
    return self.__repr__()

  def push_hit(self, ts):
    self.hits += 1
    if self.first_seen > ts:
      self.first_seen = ts
    if self.last_seen < ts:
      self.last_seen = ts

  def combine(self, hits, first_seen, last_seen):
    self.hits += hits
    if self.first_seen > first_seen:
      self.first_seen = first_seen
    if self.last_seen < last_seen:
      self.last_seen = last_seen


# BEGIN EXECUTION
ap = argparse.ArgumentParser(description='Parse domain names from input')
ap.add_argument(nargs='?', metavar='file', dest='infile', type=argparse.FileType('r'),
                  default=sys.stdin, help='Input file if not using stdin')
ap.add_argument('-d', '--delimiter', type=str, default=',', dest='delimiter', help='Input delimiter')
ap.add_argument('-t', '--top', dest='top', type=int, help='Output sorted top talking domains only')
ap.add_argument('-o', '--output-file', dest='outfile', type=str, help='Consolidated output file to update, overrides stdout')
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
          fedi_servers[url.hostname].push_hit(ts)
        else:
          fedi_servers[url.hostname] = FediServer(url.hostname, ts)

if args.outfile:
  file_servers = {}
  fh = open(args.outfile, 'r')
  for line in fh.read().split('\n'):
    if len(line) == 0:
      continue
    if line[0] == '#':
      continue

    toks = line.split(',')
    file_servers[toks[0]] = FediServer(toks[0], toks[1], toks[2])
    file_servers[toks[0]].hits = int(toks[3])

  for key,server in fedi_servers.items():
    if key in file_servers:
      file_servers[key].combine(server.hits, server.first_seen, server.last_seen)
    else:
      print("key not found")
      file_servers[key] = FediServer(key, server.first_seen, server.last_seen)
      file_servers[key].hits = server.hits
  fh.close()

  print(repr(file_servers))
  fh = open(args.outfile, 'w')
  fh.write("#domain,first_seen,last_seen,hits\n")
  for key,server in file_servers.items():
    fh.write(key + "," + str(server.first_seen) + "," + str(server.last_seen) + "," + str(server.hits) + "\n")
  fh.close()

else:
  if args.top:
    servers = [v for k,v in fedi_servers.items()]
    servers.sort(key=lambda x: x.hits, reverse=True)
    for ii in range(args.top):
      if ii < len(servers):
        print(servers[ii])
  else:
    for key, server in fedi_servers.items():
      print(server)
