#!/usr/bin/env python3

#  Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import sys
import os
import argparse
import urllib.parse

class FediServer():
  def __init__(self, domain, first_seen, last_seen=None):
    self.domain = domain
    self.hits = 1
    self.first_seen = int(first_seen)
    if last_seen:
      self.last_seen = int(last_seen)
    else:
      self.last_seen = int(first_seen)

  def __repr__(self):
    return "dn: " + self.domain + " hits:" + str(self.hits) + " fs:" + str(self.first_seen) + " ls:" + str(self.last_seen)

  def __str__(self):
    return self.__repr__()

  def push_hit(self, ts):
    self.hits += 1
    if self.first_seen > int(ts):
      self.first_seen = int(ts)
    if self.last_seen < int(ts):
      self.last_seen = int(ts)

  def combine(self, hits, first_seen, last_seen):
    self.hits += hits
    if self.first_seen > int(first_seen):
      self.first_seen = int(first_seen)
    if self.last_seen < int(last_seen):
      self.last_seen = int(last_seen)

# Parse input file and return dict of FediServers
# Takes a path to read
def parse_input(path):
  rv = {}

  if not os.path.exists(path):
    print("Error: Input file does not exist:" + path)
    exit(1)

  if not os.access(path, os.R_OK):
    print("Error: Input file not readable:" + path)
    exit(1)

  fh = open(path, 'r')
  for line in fh.read().split('\n'):
    if len(line) > 0:
      toks = line.split(args.delimiter)

      try:
        ts = int(toks[0].strip())
      except: # invalid timestamp
        continue

      for tok in toks[1:]:
        try:
          url = urllib.parse.urlparse(tok)
        except ValueError:
          continue

        if url.hostname:
          if url.hostname.strip() in rv:
            rv[url.hostname.strip()].push_hit(ts)
          else:
            rv[url.hostname.strip()] = FediServer(url.hostname.strip(), ts)

  return rv

# Parse consolidated file and return dict of FediServers
# Takes a path to the consolidated file
def parse_consolidated(path):
  rv = {}

  if not os.path.exists(path):
    return rv

  if not os.access(path, os.R_OK):
    return rv

  fh = open(path, 'r')
  for line in fh.read().split('\n'):
    if len(line) == 0:
      continue
    if line[0] == '#':
      continue

    toks = line.split(',')
    rv[toks[0].strip()] = FediServer(toks[0].strip(), toks[1].strip(), toks[2].strip())
    rv[toks[0].strip()].hits = int(toks[3].strip())

  fh.close()
  return rv

# Writes consolidated file
# Takes a path to write to, and a dict of FediServers
def write_consolidated(path, servers_dict):
  if os.path.exists(path):
    if not os.access(path, os.W_OK):
      print("Error: Output file not writable:" + path)
      exit(1)
  else:
    if len(os.path.dirname(path)) == 0:
      if not os.access('./', os.W_OK):
        print("Error: Working directory not writable")
        exit(1)
    else:
      if not os.access(os.path.dirname(path), os.W_OK):
        print("Error: Directory not writable:", os.path.dirname(path))
        exit(1)

  fh = open(path, 'w')
  servers = [v for k,v in servers_dict.items()]
  servers.sort(key=lambda x: x.domain, reverse=False)
  fh.write("#domain,first_seen,last_seen,hits\n")
  for server in servers:
    fh.write(server.domain + "," + str(server.first_seen) + "," + str(server.last_seen) + "," + str(server.hits) + "\n")

# BEGIN EXECUTION
ap = argparse.ArgumentParser(description='Process skarfed output')
ap.add_argument('-i', '--input-file', nargs='+', dest='infile', type=str, help='Input file(s). If more than 1 produce a diff between them')
ap.add_argument('-d', '--delimiter', type=str, default=',', dest='delimiter', help='Input delimiter')
ap_group = ap.add_mutually_exclusive_group()
ap_group.add_argument('-t', '--top', dest='top', type=int, help='Output sorted top talking domains only')
ap_group.add_argument('-o', '--output-file', dest='outfile', type=str, help='Consolidated output file to update, overrides stdout')
args = ap.parse_args()

if not args.infile:
  print("No input")
  exit(1)

if len(args.infile) > 2:
  print("Max 2 input files")
  exit(1)

if len(args.infile) == 1:
  fedi_servers = parse_input(args.infile[0])

  if args.outfile:
    file_servers = parse_consolidated(args.outfile)

    for key,server in fedi_servers.items():
      if key in file_servers:
        file_servers[key].combine(int(server.hits), int(server.first_seen), int(server.last_seen))
      else:
        file_servers[key] = FediServer(key, server.first_seen, server.last_seen)
        file_servers[key].hits = server.hits

    write_consolidated(args.outfile, file_servers)

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

elif len(args.infile) == 2: # Print diff of domains between both input files
  domains_1 = [v.domain for k,v in parse_input(args.infile[0]).items()]
  domains_2 = [v.domain for k,v in parse_input(args.infile[1]).items()]
  domains_1.sort()
  domains_2.sort()

  pos_1 = pos_2 = 0
  for ii in range(max(len(domains_1), len(domains_2))):
    if domains_1[pos_1] == domains_2[pos_2]:
      pos_1 += 1
      pos_2 += 1
    elif domains_1[pos_1] > domains_2[pos_2]:
      print("< " + domains_2[pos_2])
      pos_2 += 1
    elif domains_1[pos_1] < domains_2[pos_2]:
      print("> " + domains_1[pos_1])
      pos_1 += 1
