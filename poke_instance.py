#!/usr/bin/env python3

#  Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import argparse
import collections
import dns.exception
import dns.resolver
import math
import os
import multiprocessing.pool
import socket
import subprocess
import sys
import urllib.parse
import urllib.request

import fediserver

#############
# CONSTANTS #
#############

DNS_MAX_QUERIES = 5 # Number of query retries before we give up
IPV6_TEST_ADDY = '2001:500:9f::42' # just need an IPv6 address that will always be up
MAX_THREADS = 1000 # Max number of threads for the multiprocessing pool, bad things happen if this goes bigger than 1000
MIN_THREADS = 2 # Min number of threads for the multiprocessing pool
HTTPS_TIMEOUT = 10 # Timeout value for HTTPS connections in seconds

# Common relative URIs that different implementations respond on with their default installs
# Each entry in dict is a list
COMMON_URLS = collections.OrderedDict()
COMMON_URLS['bogus'] = ['no_one_would_ever_use_this_url_in_real_life']
COMMON_URLS['mastodon'] = ['actor', 'terms', 'about/more', 'explore']
COMMON_URLS['pleroma'] = ['main/all', 'main/public', 'relay']
COMMON_URLS['friendica'] = ['login']
COMMON_URLS['peertube'] = ['videos/local']
COMMON_URLS['multiple'] = ['about', '@admin']
COMMON_URLS['robots'] = ['robots.txt']
# COMMON_URLS['misskey'] = [] # This one is tough

#############
# FUNCTIONS #
#############

# Only print string s if args.verbose is True
def verbose(s):
  if args.verbose:
    print(s)

# Only print string s if args.debug is True
def debug(s):
  if args.debug:
    print(s)

# Returns the location of an executable binary
# Returns None if binary cannot be found
def find_binary(fn):
  for directory in ['/usr/bin/', '/usr/sbin/', '/bin/', '/sbin/', '/usr/local/bin/', '/usr/local/sbin/']:
    if os.path.exists(directory + fn):
      if os.access(directory + fn, os.X_OK):
        return directory + fn
  return None

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

##################
# TEST FUNCTIONS #
##################

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
    return test_ping(domain, find_binary('ping') + ' -4')
  return False

def test_ping6(domain):
  if dns_query(domain, 'AAAA'):
    return test_ping(domain, find_binary('ping') + ' -6')
  return False

# Perform a ping
# Takes a ping binary location and a domain
# Returns False if no response, otherwise returns True
def test_ping(domain, binary):
  NUM_REQS = 3
  ping_str = binary + ' -qc ' + str(NUM_REQS) + " " + domain

  try:
    result = subprocess.run(ping_str.split(), check=True, capture_output=True, text=True)
  except subprocess.TimeoutExpired as e:
    debug("test_ping:subprocess.TimeoutExpired:" + domain + " "  + str(e))
    return False
  except subprocess.CalledProcessError as e: # This "should" catch all hosts that failed to reply
    return False
  except OSError as e:
    debug("test_ping:OSERROR:" + domain + " "  + str(e))
    return False
  except subprocess.SubprocessError:
    debug("test_ping:subprocess.SubprocessError:" + domain)
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

def test_ninfo(domain):
  return test_url(domain, '.well-known/nodeinfo')

def test_ninfo2(domain):
  return test_url(domain, '.well-known/x-nodeinfo2')

# Return True if domain hosts URL
# Returns False on any failure to fetch
def test_url(domain, url):
  s = 'https://' + domain + '/' + url

  try:
    urllib.request.urlopen(s, timeout=HTTPS_TIMEOUT)
  except:
    debug('test_url:' + s + ' Fail')
    return False
  else:
    debug('test_url:' + s + ' Success')
    return True

# Fetch different domains and return True if something responds
def test_https(domain):
  for implementation,urls in COMMON_URLS.items():
    for url in urls:
      try:
        urllib.request.urlopen('https://' + domain + '/' + url, timeout=HTTPS_TIMEOUT)
      except urllib.error.HTTPError as e:
        if e.getcode() >= 400 and e.getcode() < 500:
          continue
        else:
          debug(domain + " HTTPS HTTPError:" + str(e.getcode()))
          return False
      except urllib.error.URLError as e:
        debug(domain + " HTTPS URLError:" + str(e))
        return False
      except:
        debug(domain + " HTTPS GenError")
        return False
      else:
        debug(domain + " Found:" + implementation)
        if implementation == 'bogus':
          return False
        else:
          return True

  debug(domain + " No instance or unknown instance type")
  return False

###################
# BEGIN EXECUTION #
###################

ap = argparse.ArgumentParser(description = 'Perform ordered tests on Fediverse instances. Order of tests is always r,d,4,6,n,n2,s. Output instances that pass all given tests.')

ap.add_argument('-r', '--dns-resolve', dest='dns', action='store_true', default=False, help='Output instances that resolve in DNS')
ap.add_argument('-d', '--dnssec', dest='dnssec', action='store_true', default=False, help='Output instances with DS RR in parent. No validation performed.')
ap.add_argument('-4', '--ping-ipv4', dest='ping4', action='store_true', default=False, help='Output instances answering ipv4 ICMP echo requests')
ap.add_argument('-6', '--ping-ipv6', dest='ping6', action='store_true', default=False, help='Output instances answering ipv6 ICMP echo requests')
ap.add_argument('-n', '--node-info', dest='ninfo', action='store_true', default=False, help='Output instances hosting /.well-known/nodeinfo files')
ap.add_argument('-n2', '--node-info2', dest='ninfo2', action='store_true', default=False, help='Output instances hosting /.well-known/x-nodeinfo2 files')
ap.add_argument('-s', '--https', dest='https', action='store_true', default=False, help='Output instances listening on TCP port 443')


ap.add_argument('-a', '--all-tests', dest='all', action='store_true', default=False, help='Test everything')
ap.add_argument('-g', '--debug', dest='debug', action='store_true', default=False, help='Enable debug mode, LOTS of output')
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

if not args.all and not args.ping4 and not args.ping6 and not args.dnssec \
  and not args.ninfo and not args.ninfo2 and not args.https and not args.dns:
  print("No tests requested, exiting")
  exit(1)

# Build list of instances
if args.instance:
  if args.minhits:
    print("min-hits requires input-file")
    exit(1)

  instances = []
  try:
    instances.append(fediserver.FediServer(args.instance.strip(), 0))
  except ValueError:
    print("Invalid domain:" + args.instance)
    exit(1)

else:
  instances = list(fediserver.parse_consolidated(args.infile).values())
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

if args.ninfo or args.all:
  verbose('Testing node-info:' + str(len(instances)))
  instances = perform_test(test_ninfo, instances)
  verbose('Passed node-info:' + str(len(instances)))

if args.ninfo2 or args.all:
  verbose('Testing node-info2:' + str(len(instances)))
  instances = perform_test(test_ninfo2, instances)
  verbose('Passed node-info2:' + str(len(instances)))

if args.https or args.all:
  verbose('Testing https:' + str(len(instances)))
  instances = perform_test(test_https, instances)
  verbose('Passed https:' + str(len(instances)))

if not args.totals:
  if args.outfile:
    dins = {}
    for ins in instances:
      dins[ins.domain] = ins
    fediserver.write_consolidated(args.outfile, dins)
  else:
    for ins in instances:
      print(repr(ins))
