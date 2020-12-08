#!/usr/bin/env python3

#  Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import argparse
import datetime
import dns.exception
import dns.message
import dns.resolver
import dns.rcode
import dns.rdataclass
import dns.rdatatype
import dns.query
#import ipaddress
#import itertools
import json
import math
import os
import multiprocessing.pool
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

#############
# CONSTANTS #
#############

DNS_MAX_QUERIES = 5 # Number of query retries before we give up
IPV6_TEST_ADDY = '2001:500:9f::42' # just need an IPv6 address that will alwoys be up

###########
# CLASSES #
###########

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
    try:
      rv[toks[0].strip()] = FediServer(toks[0].strip(), toks[1].strip(), toks[2].strip())
      rv[toks[0].strip()].hits = int(toks[3].strip())
    except ValueError:
      print("Error: Bad domain:" + toks[0].strip())

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


# Perform DNS query and return True if name exists
# Otherwise return False
# Handle all exceptions from dnspython
def dns_query(name, dtype):
  try:
    dns.resolver.resolve(name, dtype)
    return True
  except dns.exception.Timeout:
    return False
  except dns.resolver.NXDOMAIN:
    return False
  except dns.resolver.YXDOMAIN:
    return False
  except dns.resolver.NoAnswer:
    return False
  except dns.resolver.NoNameservers:
    print("Error: No available DNS recursive server")
    exit(1)
  except:
    print("Error: Unknown error attempting DNS resolution:" \
            + name + " " + dtype)
    exit(1)

# Returns True if domain resolves to A or AAAA
# Otherwise returns False
def test_dns(domain):
  if not dns_query(domain, 'A'):
    return dns_query(domain, 'AAAA')
  return True

# Perform test on passed list of instances
# Test is a function that returns True/False
# Return list of instances that passed
def perform_test(test, instances):
  if len(instances) < 5:
    results = []
    for ii in range(len(instances)):
      results.append(test(instances[ii].domain))
  else:
    num_threads = max(2, min(10, math.floor(len(instances) / 2))) # Kinda arbitrary
    pool = multiprocessing.pool.ThreadPool(processes=num_threads)
    results = pool.map(test, [ins.domain for ins in instances])

  for ii in range(len(results)):
    if not results[ii]:
      del instances[ii]

  return instances

###################
# BEGIN EXECUTION #
###################

ap = argparse.ArgumentParser(description = 'Perform tests on active ActivityPub Instances')
input_group = ap.add_mutually_exclusive_group()
input_group.add_argument('instance', nargs='?', type=str, help='Domains under test')
input_group.add_argument('-i', '--input-file', dest='infile', type=str, help='Consolidated list of hosts input file')
ap.add_argument('-o', '--output-file', dest='outfile', type=str, help='Consolidated output file to update, overrides stdout')
ap.add_argument('-a', '--all-tests', dest='all', action='store_true', default=False, help='Output instances passing all tests')
ap.add_argument('-d', '--dnssec', dest='dnssec', action='store_true', default=False, help='Output DNSSEC signed instances')
ap.add_argument('-f', '--fedi-test', dest='fedi', action='store_true', default=False, help='Output instances receptive to the ActivityPub protocol')
ap.add_argument('-p4', '--ping-ipv4', dest='ping4', action='store_true', default=False, help='Output instances answering ipv4 ICMP echo requests')
ap.add_argument('-p6', '--ping-ipv6', dest='ping6', action='store_true', default=False, help='Output instances answering ipv6 ICMP echo requests')
ap.add_argument('-r', '--dns-resolve', dest='dns', action='store_true', default=False, help='Output instances that resolve via DNS')
ap.add_argument('-u', '--user-agent', dest='agent', action='store', default='', type=str, help='Output instances matching passed user-agent')
args = ap.parse_args()

if not args.instance and not args.infile:
  print("No input specified")
  exit(1)

if not args.all and not args.dnssec and not args.fedi and not args.ping4 and not args.ping6 and not args.dns:
  print("No tests requested, exiting")
  exit(1)

# Build dict of instances
if args.instance:
  instances = []
  try:
    instances.append(FediServer(args.instance.strip(), 0))
  except ValueError:
    print("Invalid domain:" + args.instance)
    exit(1)
else:
  instances = parse_consolidated(args.infile).values() # This returns a view and not a list, so maybe trouble

if len(instances) == 0:
  print("Error: No instances for testing")
  exit(1)

# Is IPv6 supported on this host?
if args.ping6:
  try:
    s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    s.connect((IPV6_TEST_ADDY, 53))
    s.close()
  except OSError:
    if args.ping6:
      print("Local host does not support IPv6 yet --ping-ipv6 requested")
      exit(1)

if args.dns or args.all:
  instances = perform_test(test_dns, instances)

for ins in instances:
  print(repr(ins))
