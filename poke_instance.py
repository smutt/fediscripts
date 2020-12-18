#!/usr/bin/env python3

#  Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import argparse
import collections
import dns.exception
import dns.resolver
import json
import math
import os
import multiprocessing.pool
import resource
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
HTTPS_TIMEOUT = 10 # Timeout value for connections in seconds

# Common relative relative URLs that different implementations respond on with their default installs
# Only 'https' should contain URLs common to multiple implementations
# Bogus is used for testing if instances act on anything
# Each entry in dict is a list
COMMON_URLS = collections.OrderedDict()
COMMON_URLS['bogus'] = ['no_one_would_ever_use_this_url_in_real_life']
COMMON_URLS['mastodon'] = ['actor', 'terms', 'about/more', 'explore']
COMMON_URLS['pleroma'] = ['main/all', 'main/public', 'relay']
COMMON_URLS['friendica'] = ['login']
COMMON_URLS['peertube'] = ['videos/local']
COMMON_URLS['multiple'] = ['about', '@admin']
COMMON_URLS['https'] = ['robots.txt', '', 'index.html', 'index.htm', '.well-known/nodeinfo', '.well-known/x-nodeinfo2']
# COMMON_URLS['misskey'] = [] # This one is tough

HTTP_HDR = {}
HTTP_HDR['User-Agent'] = 'https://github.com/smutt/fediscripts'
HTTP_HDR['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
HTTP_HDR['Accept-Charset'] = 'ISO-8859-1,utf-8;q=0.7,*;q=0.3'
HTTP_HDR['Accept-Encoding'] = 'none'
HTTP_HDR['Accept-Language'] = 'en-US,en;q=0.8'
HTTP_HDR['Connection'] = 'keep-alive'

#####################
# GENERAL FUNCTIONS #
#####################

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
  if len(instances) < MIN_THREADS * 2:
    results = []
    for ii in range(len(instances)):
      results.append(test(instances[ii].domain))
  else:
    thread_count = max(MIN_THREADS, min(MAX_THREADS, math.ceil(len(instances) / 2)))
    verbose("thread_count:" + str(thread_count))
    pool = multiprocessing.pool.ThreadPool(processes=thread_count)
    results = pool.map(test, [ins.domain for ins in instances])

  # This should never happen, defensive programming
  if len(instances) != len(results) or None in results:
    print("Unknown fatal testing error")
    exit(1)

  for ii in range(len(results)):
    if not results[ii]:
      instances[ii] = None

  return [ins for ins in instances if ins]

# Perform categorization on passed list of instances
# cat is a function that categorizes instance and returns a String
# if cat returns None instance receives a category of 'Other'
# Return OrderedDict of categories and the number of instances in each
def perform_cat(cat, instances):
  if len(instances) < MIN_THREADS * 2:
    results = []
    for ii in range(len(instances)):
      results.append(cat(instances[ii].domain))
  else:
    thread_count = max(MIN_THREADS, min(MAX_THREADS, math.ceil(len(instances) / 2)))
    verbose("thread_count:" + str(thread_count))
    pool = multiprocessing.pool.ThreadPool(processes=thread_count)
    results = pool.map(cat, [ins.domain for ins in instances])

  # This should never happen, defensive programming
  if len(instances) != len(results):
    print("Unknown fatal categorization error")
    exit(1)

  results = ['other' if not x else x for x in results]

  sums = {}
  for res in results:
    if res in sums:
      sums[res] += 1
    else:
      sums[res] = 1

  # Sort sums
  rv = collections.OrderedDict()
  for ii in range(len(sums)):
    largest = list(sums)[0]
    for key,value in sums.items():
      if value > sums[largest]:
        largest = key
    rv[largest] = sums.pop(largest)

  return rv

# Fetch a URL and return its contents as a string, assumes an HTTP(S) URL
# Will retry for retries in cases of network errors
# Raises RuntimeError if something bad happens
def fetch_url(url, retries=3):
  if retries == 0:
    raise RuntimeError('fetch_url.retries_exhausted') from None

  # Ensure passed URL is a valid URL
  try:
    urllib.parse.urlparse(url)
  except ValueError as e:
    debug('fetch_url:' + url + ' bad URL ' + str(e))
    raise RuntimeError('fetch_url.BadURL') from e

  try:
    req = urllib.request.Request(url, headers=HTTP_HDR)
    with urllib.request.urlopen(req) as page:
      return page.read().decode('utf-8', 'strict')
  except urllib.error.HTTPError as e:
    debug('fetch_url:' + url + ' HTTPError:' + str(e.getcode()))
    raise RuntimeError('fetch_url.HTTPError') from e
  except urllib.error.URLError as e:
    if isinstance(e.reason, socket.timeout):
      debug('fetch_url:' + url + ' socket_timeout Retrying')
      #raise RuntimeError('fetch_url.socket_timeout') from e
    else:
      debug('fetch_url:' + url + ' URLError:' + str(e) + ' Retrying')
      #raise RuntimeError('fetch_url.URLError') from e
    return fetch_url(url, retries-1)
  except UnicodeError as e:
    debug('fetch_url:' + url + ' UnicodeError:' + str(e))
    raise RuntimeError('fetch_url.UnicodeError') from e
  except:
    debug('fetch_url:' + url + ' GenFail')
    raise RuntimeError('fetch_url.GenError') from None

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
  if not test_url(domain, COMMON_URLS['bogus'][0]):
    return test_url(domain, '.well-known/nodeinfo')
  return False

def test_ninfo2(domain):
  if not test_url(domain, COMMON_URLS['bogus'][0]):
    return test_url(domain, '.well-known/x-nodeinfo2')
  return False

# Return True if we can fetch passed relative link from domain
# Returns False on any failure to fetch
def test_url(domain, rel):
  s = 'https://' + domain + '/' + rel

  try:
    req = urllib.request.Request(s, headers=HTTP_HDR)
    urllib.request.urlopen(req)
  except urllib.error.HTTPError as e:
    debug('test_url:' + s + " HTTPError:" + str(e.getcode()))
    return False
  except urllib.error.URLError as e:
    if isinstance(e.reason, socket.timeout):
      debug('test_url:' + s + ' socket_timeout')
    else:
      debug('test_url:' + s + " URLError:" + str(e))
    return False
  except:
    debug('test_url:' + s + ' GenFail')
    return False
  else:
    debug('test_url:' + s + ' Success')
    return True

# Returns True if any common URL can be fetched from domain
# If we fetch none of the URLs, but we only get http client errors, return True
def test_https(domain):
  for rel in COMMON_URLS['https']:
    s = 'https://' + domain + '/' + rel

    try:
      req = urllib.request.Request(s, headers=HTTP_HDR)
      urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
      if e.getcode() >= 400 and e.getcode() < 500:
        continue
      else:
        debug('test_https:' + s + " HTTPError:" + str(e.getcode()))
        return False
    except urllib.error.URLError as e:
      if isinstance(e.reason, socket.timeout):
        debug('test_url:' + s + ' socket_timeout')
      else:
        debug('test_url:' + s + " URLError:" + str(e))
      return False
    except:
      debug('test_https:' + s + " GenError")
      return False
    else:
      debug('test_https:' + s + " Success")
      return True

  debug('test_url:' + s + ' DefaultSuccess')
  return True

#################
# CAT FUNCTIONS #
#################

# Categorize based on advertised schemas
def cat_schema_sw_name(domain):
  try:
    schemas = fetch_url('https://' + domain + '/.well-known/nodeinfo')
  except RuntimeError as e:
    debug('cat_schema_sw_name:' + domain + ' schemas.RuntimeError:' + str(e))
    return None

  try:
    j_schemas = json.loads(schemas)
  except json.JSONDecodeError as e:
    debug('cat_schema_sw_name:' + domain + ' schemas.JSONDecodeError:' + str(e))
    return None

  # Be super careful when reading, many ways for this to break
  if 'links' in j_schemas:
    if isinstance(j_schemas['links'], list):
      if len(j_schemas['links']) > 0:
        if 'href' in j_schemas['links'][-1]:
          try:
            nodeinfo = fetch_url(j_schemas['links'][-1]['href'])
          except RuntimeError as e:
            debug('cat_schema_sw_name:' + domain + ' nodeinfo.RuntimeError:' + str(e))
            return None

          try:
            j_nodeinfo = json.loads(nodeinfo)
          except json.JSONDecodeError as e:
            debug('cat_schema_sw_name:' + domain + ' nodeinfo.JSONDecodeError' + str(e))
            return None

          if 'software' in j_nodeinfo:
            if 'name' in j_nodeinfo['software']:
              return j_nodeinfo['software']['name'].lower()

  return None

# Categorize based on URLs common to different instance implementations
def cat_url(domain):
  for implementation,rels in COMMON_URLS.items():
    for rel in rels:
      s = 'https://' + domain + '/' + rel

      try:
        req = urllib.request.Request(s, headers=HTTP_HDR)
        urllib.request.urlopen(req)
      except urllib.error.HTTPError as e:
        if isinstance(e.reason, socket.timeout):
          debug('cat_url:' + s + ' socket_timeout')
          return None
        elif e.getcode() >= 400 and e.getcode() < 500:
          continue
        else:
          debug('cat_url:' + s + ' HTTPError:' + str(e.getcode()))
          return None
      except urllib.error.URLError as e:
        debug('cat_url:' + s + ' URLError:' + str(e) + ' ' + str(e.args))
        return None
      except:
        debug('cat_url:' + s + ' GenError')
        return None
      else:
        debug('cat_url:' + s + ' Found:' + implementation)
        if implementation == 'bogus' or implementation == 'https':
          return None
        else:
          return implementation

  debug('cat_url:' + domain + ' None')
  return None

# Categorize based on how many dots in the domain
def cat_ndots(domain):
  return str(domain.count('.'))

###################
# BEGIN EXECUTION #
###################

ap = argparse.ArgumentParser(description = 'Perform ordered tests on Fediverse instances. Order of tests is always r,d,4,6,s,n,n2. Output instances that pass all given tests.')

ap.add_argument('-r', '--dns-resolve', dest='dns', action='store_true', default=False, help='Output instances that resolve in DNS')
ap.add_argument('-d', '--dnssec', dest='dnssec', action='store_true', default=False, help='Output instances with DS RR in parent. No validation performed.')
ap.add_argument('-4', '--ping-ipv4', dest='ping4', action='store_true', default=False, help='Output instances answering ipv4 ICMP echo requests')
ap.add_argument('-6', '--ping-ipv6', dest='ping6', action='store_true', default=False, help='Output instances answering ipv6 ICMP echo requests')
ap.add_argument('-s', '--https', dest='https', action='store_true', default=False, help='Output instances running an HTTPS service, somewhat guesswork.')
ap.add_argument('-n', '--node-info', dest='ninfo', action='store_true', default=False, help='Output instances hosting /.well-known/nodeinfo files')
ap.add_argument('-n2', '--node-info2', dest='ninfo2', action='store_true', default=False, help='Output instances hosting /.well-known/x-nodeinfo2 files')

ap.add_argument('-a', '--all-tests', dest='all', action='store_true', default=False, help='Test everything')
ap.add_argument('-g', '--debug', dest='debug', action='store_true', default=False, help='Enable debug mode, LOTS of output')
ap.add_argument('-t', '--totals', dest='totals', action='store_true', default=False, help='Print test passing totals only. Sets verbose and overrides output-file.')
ap.add_argument('-v', '--verbose', dest='verbose', action='store_true', default=False, help='Verbose output')
ap.add_argument('-m', '--min-hits', dest='minhits', type=int, default=None, help='Only test instances with hits >= MINHITS. Requires input-file.')

input_group = ap.add_mutually_exclusive_group()
input_group.add_argument('instance', nargs='?', type=str, help='Domains under test')
input_group.add_argument('-i', '--input-file', dest='infile', type=str, help='Consolidated list of hosts input file')

ap.add_argument('-o', '--output-file', dest='outfile', type=str, help='Consolidated output file to update, overrides stdout')
ap.add_argument('-cd', '--cat-ndots', dest='catndots', action='store_true', default=False, help='Categorize by number of dots in the domain.')
ap.add_argument('-cn', '--cat-name', dest='catname', action='store_true', default=False, help='Categorize by software name shown in /.well-known/nodeinfo. Overrides output-file.')
ap.add_argument('-cu', '--cat-url', dest='caturl', action='store_true', default=False, help='Categorize by guessing implementation type by fetchable common URLs. Overrides output-file. Broken.')
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

# Set max number of open files for system
_,nofiles_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (nofiles_hard,nofiles_hard))

# Set timeout for all connections
# This SHOULD work according to this, https://docs.python.org/3/howto/urllib2.html
socket.setdefaulttimeout(HTTPS_TIMEOUT)

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

if args.ninfo or args.all:
  verbose('Testing node-info:' + str(len(instances)))
  instances = perform_test(test_ninfo, instances)
  verbose('Passed node-info:' + str(len(instances)))

if args.ninfo2 or args.all:
  verbose('Testing node-info2:' + str(len(instances)))
  instances = perform_test(test_ninfo2, instances)
  verbose('Passed node-info2:' + str(len(instances)))

if not args.totals:
  if args.outfile:
    dins = {}
    for ins in instances:
      dins[ins.domain] = ins
    fediserver.write_consolidated(args.outfile, dins)
  else:
    for ins in instances:
      print(repr(ins))

if args.catndots:
  for cat,tot in perform_cat(cat_ndots, instances).items():
    print('cat-ndots:' + cat + ':' + str(tot))
if args.catname:
  for cat,tot in perform_cat(cat_schema_sw_name, instances).items():
    print('cat-name:' + cat + ':' + str(tot))
if args.caturl:
  for cat,tot in perform_cat(cat_url, instances).items():
    print('cat-url:' + cat + ':' + str(tot))
