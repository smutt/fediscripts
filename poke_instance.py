#!/usr/bin/env python3

#  Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import argparse
import collections
import dns.exception
import dns.resolver
import http.client
import json
import math
import multiprocessing.pool
import os
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
HTTPS_RETRIES = 3 # Number of attempts we make when testing or fetching HTTPS URLs

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

HTTP_HDR = {} # Headers sent with HTTPS requests
HTTP_HDR['User-Agent'] = 'https://github.com/smutt/fediscripts'
HTTP_HDR['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
HTTP_HDR['Accept-Charset'] = 'ISO-8859-1,utf-8;q=0.7,*;q=0.3'
HTTP_HDR['Accept-Encoding'] = 'none'
HTTP_HDR['Accept-Language'] = 'en-US,en;q=0.8'
HTTP_HDR['Connection'] = 'keep-alive'

USER_CATS = collections.OrderedDict() # A mapping users categories for instances to their display strings
USER_CATS[100] = '0-100'
USER_CATS[500] = '101-500'
USER_CATS[1000] = '501-1k'
USER_CATS[5000] = '1001-5k'
USER_CATS[10000] = '5001-10k'
USER_CATS[sys.maxsize] = '>10k'

SUMS = {} # A mapping of SUMS CLI arguments to nodeinfo attributes
SUMS['local-posts'] = ['usage', 'localPosts']
SUMS['users-total'] = ['usage', 'users', 'total']
SUMS['users-active-month'] = ['usage', 'users', 'activeMonth']
SUMS['users-active-halfyear'] = ['usage', 'users', 'activeHalfyear']

#####################
# GENERAL FUNCTIONS #
#####################

# Only print string s if args.verbose is True
def verbose(s):
  if args.verbose:
    try:
      print(s, flush=True)
    except IOError:
      exit(1)

# Only print string s if args.debug is True
def debug(s):
  if args.debug:
    try:
      print(s, flush=True)
    except IOError:
      exit(1)

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
    verbose("test_thread_count:" + str(thread_count))
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

# Total an integer from nodeinfo for multiple instances
# Return integer value
def perform_total(attr, instances):
  if len(instances) < MIN_THREADS * 2:
    results = []
    for ii in range(len(instances)):
      results.append(fetch_nodeinfo_attr(instances[ii].domain, attr))
  else:
    thread_count = max(MIN_THREADS, min(MAX_THREADS, math.ceil(len(instances) / 2)))
    verbose("total_thread_count:" + str(thread_count))
    pool = multiprocessing.pool.ThreadPool(processes=thread_count)
    results = pool.starmap(fetch_nodeinfo_attr, [(ins.domain, attr) for ins in instances])

  # This should never happen, defensive programming
  if len(instances) != len(results):
    print("Unknown fatal totaling error")
    exit(1)

  total = 0
  for res in results:
    if res:
      if isinstance(res, int):
        if res > 0:
          total += res
      if isinstance(res, str):
        try:
          res = int(res)
        except ValueError as e:
          debug('perform_total:' + ' ValueError:' + str(e))
          continue
        if res > 0:
          total += res

  return total

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
    verbose("cat_thread_count:" + str(thread_count))
    pool = multiprocessing.pool.ThreadPool(processes=thread_count)
    results = pool.map(cat, [ins.domain for ins in instances])

  # This should never happen, defensive programming
  if len(instances) != len(results):
    print("Unknown fatal categorization error")
    exit(1)

  results = ['Other' if not x else x for x in results]

  sums = {}
  total = 0
  for res in results:
    total += 1
    if res in sums:
      sums[res] += 1
    else:
      sums[res] = 1

  # Sort sums
  rv = collections.OrderedDict()
  rv['Total'] = total
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
def fetch_url(url, retries=HTTPS_RETRIES):
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

# Fetch an attribute from a nodeinfo schema
# Takes a domain and an attr, attr is a list of keys in descending order representing the requested attribute
# String keys assume dicts, while int keys assume lists
# Returns attribute or None if it does not exist
def fetch_nodeinfo_attr(domain, attr):
  try:
    schemas = fetch_url('https://' + domain + '/.well-known/nodeinfo')
  except RuntimeError as e:
    debug('fetch_nodeinfo_attr:' + domain + ' schemas.RuntimeError:' + str(e))
    return None

  try:
    j_schemas = json.loads(schemas)
  except json.JSONDecodeError as e:
    debug('fetch_nodeinfo_attr:' + domain + ' schemas.JSONDecodeError:' + str(e))
    return None

  if 'links' in j_schemas:
    if isinstance(j_schemas['links'], list):
      if len(j_schemas['links']) > 0:
        if 'href' in j_schemas['links'][-1]: # nodeinfo standard says to always take the last one
          try:
            nodeinfo = fetch_url(j_schemas['links'][-1]['href'])
          except RuntimeError as e:
            debug('fetch_nodeinfo_attr:' + domain + ' nodeinfo.RuntimeError:' + str(e))
            return None

          try:
            j_nodeinfo = json.loads(nodeinfo)
          except json.JSONDecodeError as e:
            debug('fetch_nodeinfo_attr:' + domain + ' nodeinfo.JSONDecodeError' + str(e))
            return None

          active_stem = j_nodeinfo
          for key in attr:
            if isinstance(key, int): # Caller expects a list here
              if len(active_stem) > key:
                active_stem = active_stem[key]
              else:
                debug('fetch_nodeinfo_attr:' + domain + ' invalidIndex:' + str(key))
                return None
            elif isinstance(key, str): # Caller expects a dict here
              if key in active_stem:
                active_stem = active_stem[key]
              else:
                debug('fetch_nodeinfo_attr:' + domain + ' invalidKey:' + key)
                return None
          return active_stem
  return None

##################
# TEST FUNCTIONS #
##################

# Returns True if domain resolves to A or AAAA
# Otherwise returns False
def test_dns(domain):
  if not dns_query(domain, 'A'):
    return dns_query(domain, 'AAAA')
  return True

# Return True if DS and DNSKEY records present
# Otherwise returns False
def test_dnssec(domain):
  try:
    cname = dns.resolver.resolve(domain, search=True).__dict__['canonical_name'].to_text()
  except  dns.exception.DNSException as e:
    debug('test_dnssec:cname:' + domain + ' ' + str(e))
    return False

  try:
    zone = dns.resolver.zone_for_name(cname).to_text()
  except dns.exception.DNSException as e:
    debug('test_dnssec:zone:' + cname + ' ' + str(e))
    return False

  if dns_query(zone, 'DS'):
    return dns_query(zone, 'DNSKEY')
  return False

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
  return test_url(domain, '.well-known/nodeinfo', 'json')

def test_ninfo2(domain):
  return test_url(domain, '.well-known/x-nodeinfo2', 'json')

# Return True if we can fetch headers of passed relative link from domain
# if string content_type is passed, it must be present in response content-type
# Returns False on any failure to fetch, or if content_type doesn't match HTTP content-type
# Retries on connection failure
def test_url(domain, rel, content_type=None, retries=HTTPS_RETRIES):
  s = 'https://' + domain + '/' + rel

  if retries == 0:
    debug('test_url:' + s + ' retries.exhausted')
    return False

  try:
    req = urllib.request.Request(s, headers=HTTP_HDR)
    with urllib.request.urlopen(req) as page:
      if content_type:
        page_c_type = page.getheader('content-type')
        if page_c_type:
          if content_type in page_c_type:
            return True
        debug('test_url:' + s + ' BadHTTPContent-type')
        return False
  except urllib.error.HTTPError as e:
    debug('test_url:' + s + " HTTPError:" + str(e.getcode()))
    return False
  except urllib.error.URLError as e:
    if isinstance(e.reason, socket.timeout):
      debug('test_url:' + s + ' socket_timeout Retrying')
    else:
      debug('test_url:' + s + " URLError:" + str(e) + ' Retrying')
    return test_url(domain, rel, content_type, retries-1)
  except:
    debug('test_url:' + s + ' GenFail')
    return False
  else:
    debug('test_url:' + s + ' Success')
    return True

  ''' This code proved incompatible with multiprocessing
  lesson => do not use the requests library with multiprocessing
  try:
    resp = requests.head(s, headers=HTTP_HDR, timeout=HTTPS_TIMEOUT)
  except requests.ConnectionError as e:
    debug('test_url:' + s + ' ConnectionError')# + repr(e))
    return False
  except requests.HTTPError as e:
    debug('test_url:' + s + ' HTTPError')# + str(e))
    return False
  except requests.URLRequired as e:
    debug('test_url:' + s + ' BadURL')# + str(e))
    return False
  except requests.TooManyRedirects as e:
    debug('test_url:' + s + ' TooManyRedirects')# + str(e))
    return False
  except requests.ConnectTimeout as e:
    debug('test_url:' + s + ' ConnectTimeout')# + str(e))
    return False
  except requests.ReadTimeout as e:
    debug('test_url:' + s + ' ServerReadTimeout')# + str(e))
    return False
  except requests.RequestException as e:
    debug('test_url:' + s + ' RequestException')# + str(e))
    return False
  except:
    debug('test_url:' + s + ' GenFail')
    return False
  else:
    if not resp.ok:
      debug('test_url:' + s + ' ' + resp.reason)
      return False

    if content_type:
      if 'content-type' not in resp.headers:
        debug('test_url:' + s + ' content_type not present in HTTP headers')
        return False
      if content_type.lower() not in resp.headers['content-type'].lower():
        debug('test_url:' + s + ' wrong content_type in HTTP headers')
        return False
    return True
  '''

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

# Categorize based on number of local posts in nodeinfo
def cat_local_posts(domain):
  local_posts = fetch_nodeinfo_attr(domain, ['usage', 'localPosts'])
  if not isinstance(local_posts, int):
    debug('cat_local_posts:' + domain + ' invalidData.not_int')
    return None
  if local_posts < 0:
    debug('cat_local_posts:' + domain + ' invalidData.neg_int')
    return None

  if local_posts < 1000:
    return '0-1k'
  if local_posts < 10000:
    return '1k-10k'
  if local_posts < 100000:
    return '10k-100k'
  if local_posts < 1000000:
    return '100k-1m'
  return '>1m'

# Categorize based on total number of users
def cat_users_total(domain):
  users = fetch_nodeinfo_attr(domain, ['usage', 'users', 'total'])
  if not isinstance(users, int):
    debug('cat_users_total:' + domain + ' invalidData.not_int')
    return None
  if users < 0:
    debug('cat_users_total:' + domain + ' invalidData.neg_int')
    return None

  for num,display in USER_CATS.items():
    if users <= num:
      return display

# Categorize based on active monthly users
def cat_users_active_month(domain):
  users = fetch_nodeinfo_attr(domain, ['usage', 'users', 'activeMonth'])
  if not isinstance(users, int):
    debug('cat_users_active_month:' + domain + ' invalidData.not_int')
    return None
  if users < 0:
    debug('cat_users_active_month:' + domain + ' invalidData.neg_int')
    return None

  for num,display in USER_CATS.items():
    if users <= num:
      return display

# Categorize based on active half-yearly users
def cat_users_active_halfyear(domain):
  users = fetch_nodeinfo_attr(domain, ['usage', 'users', 'activeHalfyear'])
  if not isinstance(users, int):
    debug('cat_users_active_halfyear:' + domain + ' invalidData.not_int')
    return None
  if users < 0:
    debug('cat_users_active_halfyear:' + domain + ' invalidData.neg_int')
    return None

  for num,display in USER_CATS.items():
    if users <= num:
      return display

# Categorize based on software name in nodeinfo
def cat_software(domain):
  return fetch_nodeinfo_attr(domain, ['software', 'name'])

# Categorize based on URLs common to different instance implementations
# This doesn't really work and never really will
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

# A mapping of categorization methods to their python functions
# Must come after function definitions
CAT_METHODS = {}
CAT_METHODS['ndots'] = cat_ndots
CAT_METHODS['software'] = cat_software
CAT_METHODS['url'] = cat_url
CAT_METHODS['local-posts'] = cat_local_posts
CAT_METHODS['users-total'] = cat_users_total
CAT_METHODS['users-active-month'] = cat_users_active_month
CAT_METHODS['users-active-halfyear'] = cat_users_active_halfyear

ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                               description = 'Perform ordered tests on Fediverse instances. Output instances that pass all given tests.',
                               epilog =
'''
<Mutually exclusive arguments>
INSTANCE and --input-file are mutually exclusive
--output-file, --categorize and --sum are all mutually exclusive

<Test execution order>
dns-resolve -> dnssec -> ping-ipv4 -> ping-ipv6 -> https -> node-info -> node-info2

<Available categorization methods>
local-posts -> Categorize by number of local posts shown in nodeinfo.
ndots -> Categorize by number of dots in the domain.
software -> Categorize by software name shown in nodeinfo.
url -> {Experimental} Categorize by guessing implementation type by fetchable common URLs.
users-total -> Categorize by total users shown in nodeinfo.
users-active-month -> Categorize by monthly active users shown in nodeinfo.
users-active-halfyear -> Categorize by half-yearly(180 days) active users shown in nodeinfo.

<Available sums>
local-posts -> Sum up local posts shown in nodeinfo.
users-total ->  Sum up total users shown in nodeinfo.
users-active-month -> Sum up monthly active users shown in nodeinfo.
users-active-halfyear -> Sum up half-yearly(180 days) active users shown in nodeinfo.
'''
                               )
ap.add_argument('-r', '--dns-resolve', dest='dns', action='store_true', default=False, help='Output instances that resolve in DNS')
ap.add_argument('-d', '--dnssec', dest='dnssec', action='store_true', default=False, help='Output instances with associated DS and DNSKEY RRs. No validation performed.')
ap.add_argument('-4', '--ping-ipv4', dest='ping4', action='store_true', default=False, help='Output instances answering ipv4 ICMP echo requests')
ap.add_argument('-6', '--ping-ipv6', dest='ping6', action='store_true', default=False, help='Output instances answering ipv6 ICMP echo requests')
ap.add_argument('-e', '--https', dest='https', action='store_true', default=False, help='Output instances running an encrypted HTTPS service, somewhat guesswork.')
ap.add_argument('-n', '--node-info', dest='ninfo', action='store_true', default=False, help='Output instances hosting /.well-known/nodeinfo files')
ap.add_argument('-n2', '--node-info2', dest='ninfo2', action='store_true', default=False, help='Output instances hosting /.well-known/x-nodeinfo2 files')

ap.add_argument('-a', '--all-tests', dest='all', action='store_true', default=False, help='Test everything')
ap.add_argument('-g', '--debug', dest='debug', action='store_true', default=False, help='Enable debug mode, LOTS of output')
ap.add_argument('-j', '--json', dest='json', action='store_true', default=False, help='Output to JSON instead of CSV. Overrides output-file.')
ap.add_argument('-t', '--totals', dest='totals', action='store_true', default=False, help='Print test passing totals and categorizations. Does not output consolidated instances. Overrides output-file.')
ap.add_argument('-v', '--verbose', dest='verbose', action='store_true', default=False, help='Verbose output')
ap.add_argument('-m', '--min-hits', dest='minhits', type=int, default=None, help='Only test instances with hits >= MINHITS. Requires input-file.')

input_group = ap.add_mutually_exclusive_group()
input_group.add_argument('instance', metavar='INSTANCE', nargs='?', type=str, help='Test a single instance')
input_group.add_argument('-i', '--input-file', dest='infile', type=str, help='Consolidated list of hosts input file')

output_group = ap.add_mutually_exclusive_group()
output_group.add_argument('-o', '--output-file', dest='outfile', type=str, help='Consolidated output file to update')
output_group.add_argument('-c', '--categorize', metavar='METHOD', dest='cat', nargs='+', help='Categorize passing instances by one or more qualifiers')
output_group.add_argument('-s', '--sum', metavar='SUM', dest='sums', nargs='+', help='Sum up nodeinfo integer values retrieved from passing instances')
args = ap.parse_args()

if not args.instance and not args.infile:
  print("No input specified")
  exit(1)

if not args.all and not args.ping4 and not args.ping6 and not args.dnssec \
  and not args.ninfo and not args.ninfo2 and not args.https and not args.dns:
  print("No tests requested, exiting")
  exit(1)

if args.json or args.totals:
  args.outfile = None

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
  elif args.json:
    print(json.dumps([ins.__dict__ for ins in instances]))
  else:
    for ins in instances:
      print(repr(ins))

if args.cat:
  for method,func in CAT_METHODS.items():
    if method in args.cat:
      if args.json:
        print(json.dumps({method:perform_cat(func, instances)}))
      else:
        for cat,tot in perform_cat(func, instances).items():
          print(method + ':' + cat + ':' + str(tot))

if args.sums:
  for method,attr in SUMS.items():
    if method in args.sums:
      if args.json:
        print(json.dumps({method:perform_total(attr, instances)}))
      else:
        print(method + ':' + str(perform_total(attr, instances)))
