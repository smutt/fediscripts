#!/usr/bin/env python3

#  Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import argparse
import dns.exception
import dns.resolver
import math
import os
import multiprocessing.pool
import socket
import subprocess
import sys
#import threading
import urllib.parse
import urllib.request
import string

#############
# CONSTANTS #
#############

DNS_MAX_QUERIES = 5 # Number of query retries before we give up
IPV6_TEST_ADDY = '2001:500:9f::42' # just need an IPv6 address that will alwoys be up
MAX_THREADS = 100 # Max number of threads for the multiprocessing pool
MIN_THREADS = 2 # Min number of threads for the multiprocessing pool

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
    return self.domain + ',' + str(self.first_seen) + ',' + str(self.last_seen) + ',' + str(self.hits)

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

# Returns the location of an executable binary
# Returns None if binary cannot be found
def find_binary(fn):
  for directory in ['/usr/bin/', '/usr/sbin/', '/bin/', '/sbin/', '/usr/local/bin/', '/usr/local/sbin/']:
    if os.path.exists(directory + fn):
      if os.access(directory + fn, os.X_OK):
        return directory + fn
  return None

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
  except dns.resolver.NoNameservers: # SERVFAIL
    return False
  except:
    print("Error: Unknown error attempting DNS resolution:" \
            + name + " " + dtype)
    return False

# Perform test on passed list of instances
# Test is a function that returns True/False
# Return list of instances that passed
def perform_test(test, instances):
  if len(instances) < 5:
    results = []
    for ii in range(len(instances)):
      results.append(test(instances[ii].domain))
  else:
    thread_count = max(MIN_THREADS, min(MAX_THREADS, math.ceil(len(instances) / 2)))
    verbose("thread_count:" + str(thread_count))
    pool = multiprocessing.pool.ThreadPool(processes=thread_count)
    results = pool.map(test, [ins.domain for ins in instances])

  for ii in range(len(results)):
    if not results[ii]:
      instances[ii] = None

  return [ins for ins in instances if ins]

# Returns True if domain resolves to A or AAAA
# Otherwise returns False
def test_dns(domain):
  if not dns_query(domain, 'A'):
    return dns_query(domain, 'AAAA')
  return True

# Return True if domain zone contains DS record
# OTherwise returns False
def test_dnssec(domain):
  try:
    zone = dns.resolver.zone_for_name(domain).to_text()
  except dns.resolver.NoRootSOA:
    return False
  except:
    return False

  return dns_query(zone, 'DS')

# Wrapper functions for test_ping()
def test_ping4(domain):
  if dns_query(domain, 'A'):
    return test_ping(find_binary('ping') + ' -4', domain)
  return False

def test_ping6(domain):
  if dns_query(domain, 'AAAA'):
    return test_ping(find_binary('ping') + ' -6', domain)
  return False

# Perform a ping
# Takes a ping binary location and a domain
# Returns False if no response, otherwise returns True
def test_ping(binary, domain):
  NUM_REQS = 3
  ping_str = binary + ' -qc ' + str(NUM_REQS) + " " + domain

  try:
    result = subprocess.run(ping_str.split(), check=True, capture_output=True, text=True)
  except subprocess.TimeoutExpired as e:
    print("test_ping:subprocess.TimeoutExpired:" + domain + " "  + str(e))
    return False
  except subprocess.CalledProcessError as e: # This "should" catch all hosts that failed to reply
    return False
  except OSError as e:
    print("test_ping:OSERROR:" + domain + " "  + str(e))
    return False
  except subprocess.SubprocessError:
    print("test_ping:subprocess.SubprocessError:" + domain)
    return False

  try:
    result.check_returncode()
  except CalledProcessError:
    return False

  if not result.stdout:
    return False

  for line in result.stdout.split('\n'):
    if '% packet loss' in line:
      if line.split('%')[0][:-3] == '100':
        return False # This "should" never actually happen
  return True

# Fetch domain/index.html and return True if something responds
# Should also return True on HTTP 404
def test_https(domain):
  try:
    urllib.request.urlopen('https://' + domain + '/index.html')
  except urllib.error.HTTPError as e:
    #verbose("HTTPS HTTPError:" + str(e))
    return True
  except urllib.error.URLError as e:
    #verbose(domain + " HTTPS URLError:" + str(e))
    return False
  else:
    return True

# Only print string s if args.verbose is True
def verbose(s):
  if args.verbose:
    print(s)

###################
# BEGIN EXECUTION #
###################

ap = argparse.ArgumentParser(description = 'Perform tests on Fediverse instances. Output instances that pass all given tests.')

ap.add_argument('-4', '--ping-ipv4', dest='ping4', action='store_true', default=False, help='Output instances answering ipv4 ICMP echo requests')
ap.add_argument('-6', '--ping-ipv6', dest='ping6', action='store_true', default=False, help='Output instances answering ipv6 ICMP echo requests')
ap.add_argument('-d', '--dnssec', dest='dnssec', action='store_true', default=False, help='Output instances with DS RR in parent. No validation performed.')
ap.add_argument('-s', '--https', dest='https', action='store_true', default=False, help='Output instances listening on TCP port 443')
ap.add_argument('-r', '--dns-resolve', dest='dns', action='store_true', default=False, help='Output instances that resolve in DNS')

ap.add_argument('-a', '--all-tests', dest='all', action='store_true', default=False, help='Test everything')
ap.add_argument('-t', '--totals', dest='totals', action='store_true', default=False, help='Print test passing totals only. Sets verbose and overrides output-file.')
ap.add_argument('-v', '--verbose', dest='verbose', action='store_true', default=False, help='Verbose output')
ap.add_argument('-m', '--min-hits', dest='minhits', type=int, default=None, help='Only test instances with hits >= MINHITS. Requires input-file.')

input_group = ap.add_mutually_exclusive_group()
input_group.add_argument('instance', nargs='?', type=str, help='Domains under test')
input_group.add_argument('-i', '--input-file', dest='infile', type=str, help='Consolidated list of hosts input file')
ap.add_argument('-o', '--output-file', dest='outfile', type=str, help='Consolidated output file to update, overrides stdout')

args = ap.parse_args()

if args.totals:
  args.verbose = True

if not args.instance and not args.infile:
  print("No input specified")
  exit(1)

if not args.all and not args.ping4 and not args.ping6 and not args.dnssec and not args.https and not args.dns:
  print("No tests requested, exiting")
  exit(1)

# Build list of instances
if args.instance:
  if args.minhits:
    print("min-hits requires input-file")
    exit(1)

  instances = []
  try:
    instances.append(FediServer(args.instance.strip(), 0))
  except ValueError:
    print("Invalid domain:" + args.instance)
    exit(1)

else:
  instances = list(parse_consolidated(args.infile).values())
  if args.minhits:
    instances = [ins for ins in instances if ins.hits >= args.minhits]

if len(instances) == 0:
  print("Error: No instances for testing")
  exit(1)

if args.dns or args.all:
  verbose('Testing DNS resolution:' + str(len(instances)))
  instances = perform_test(test_dns, instances)
  verbose('Passed DNS resolution:' + str(len(instances)))

if args.dnssec or args.all:
  verbose('Testing DNSSEC:' + str(len(instances)))
  instances = perform_test(test_dnssec, instances)
  verbose('Passed DNSSEC:' + str(len(instances)))

if args.ping4 or args.all:
  verbose('Testing ping-ipv4:' + str(len(instances)))
  instances = perform_test(test_ping4, instances)
  verbose('Passed ping-ipv4:' + str(len(instances)))

if args.ping6 or args.all:
  ipv6_support = True
  try:
    s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    s.connect((IPV6_TEST_ADDY, 53))
    s.close()
  except OSError:
   ipv6_support = False
   if args.ping6:
      print("Error: Local host does not support IPv6, and --ping-ipv6 requested")
      exit(1)

  if ipv6_support:
    verbose('Testing ping-ipv6:' + str(len(instances)))
    instances = perform_test(test_ping6, instances)
    verbose('Passed ping-ipv6:' + str(len(instances)))

if args.https or args.all:
  verbose('Testing https:' + str(len(instances)))
  instances = perform_test(test_https, instances)
  verbose('Passed https:' + str(len(instances)))

if not args.totals:
  if args.outfile:
    dins = {}
    for ins in instances:
      dins[ins.domain] = ins
    write_consolidated(args.outfile, dins)
  else:
    for ins in instances:
      print(repr(ins))
