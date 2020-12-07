#!/usr/bin/env python3

#  Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import argparse
import datetime
#import dns.exception
#import dns.message
#import dns.resolver
#import dns.rcode
#import dns.rdataclass
#import dns.rdatatype
#import dns.query
#import ipaddress
#import itertools
import json
import os
#import multiprocessing.pool
import random
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse
import string

class FediServer():
  DOMAIN_CHARS = string.ascii_letters + string.digits + '-' + '.'

  def __init__(self, domain, first_seen, last_seen=None):
    self.domain = self.confirm_domain(domain.lower().strip())
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

  # Test passed string to confirm it is valid domain
  # Rightmost character can be '.', but we return without
  # Return valid domain
  def confirm_domain(self, domain):
    for s in domain:
      if s not in self.DOMAIN_CHARS:
        raise ValueError

    domain = domain.rstrip('.')
    if domain[0] == '.':
      raise ValueError

    for tok in domain.split('.'):
      if len(tok) == 0 :
        raise ValueError
      if len(tok) > 63:
        raise ValueError
      if tok.startswith('-'):
        raise ValueError
      if tok.endswith('-'):
        raise ValueError

    return domain

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

#############
# FUNCTIONS #
#############

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


###################
# BEGIN EXECUTION #
###################

ap = argparse.ArgumentParser(description = 'Perform tests on active ActivityPub Instances')
input_group = ap.add_mutually_exclusive_group()
input_group.add_argument('instance', nargs='?', type=str, help='Domains under test')
input_group.add_argument('-i', '--input-file', dest='infile', type=str, help='Consolidated list of hosts input file')
ap.add_argument('-o', '--output-file', dest='outfile', type=str, help='Consolidated output file to update, overrides stdout')
ap.add_argument('-a', '--all-tests', action='store_true', default=False, help='Output instances passing all tests')
ap.add_argument('-d', '--dnssec', action='store_true', default=False, help='Output DNSSEC signed instances')
ap.add_argument('-f', '--fedi-test', action='store_true', default=False, help='Output instances receptive to the ActivityPub protocol')
ap.add_argument('-p', '--ping', action='store_true', default=False, help='Output instances answering ICMP echo requests')
ap.add_argument('-r', '--dns-resolve', action='store_true', default=False, help='Output instances that resolve via DNS')
ap.add_argument('-u', '--user-agent', action='store', default='', type=str, help='Output instances matching passed user-agent')
args = ap.parse_args()

if args.instance:
  instances = {}
  try:
    instances[args.instance] = FediServer(args.instance.strip(), 0)
  except:
    print("Invalid domain:" + args.instance)
    exit(1)
else:
  instances = parse_consolidated(args.infile)

for ins in [v for k,v in instances.items()]:
  print(repr(ins))
