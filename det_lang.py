#!/usr/bin/env python3

#  Copyright (C) 2021, Andrew McConachie, <andrew@depht.com>

import sys
import os
import argparse
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup as bs
from textblob import TextBlob
import socket

# Constants
HTTPS_RETRIES = 3 # Number of attempts we make when testing or fetching HTTPS URLs
HTTPS_TIMEOUT = 10 # Timeout value for connections in seconds

# Set timeout for all connections
# This SHOULD work according to this, https://docs.python.org/3/howto/urllib2.html
socket.setdefaulttimeout(HTTPS_TIMEOUT)

HTTP_HDR = {} # Headers sent with HTTPS requests
HTTP_HDR['User-Agent'] = 'https://github.com/smutt/fediscripts'
HTTP_HDR['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
HTTP_HDR['Accept-Charset'] = 'ISO-8859-1,utf-8;q=0.7,*;q=0.3'
HTTP_HDR['Accept-Encoding'] = 'none'
HTTP_HDR['Accept-Language'] = 'en-US,en;q=0.8'
HTTP_HDR['Connection'] = 'keep-alive'

# Only print string s if args.debug is True
def debug(s):
  if args.debug:
    try:
      print(s, flush=True)
    except IOError:
      exit(1)

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

# Parse input and return list of URLs
# Takes a skarf file as string
def parse_skarf(skarf_str):
  rv = []

  for line in skarf_str.split('\n'):
    if len(line) > 0:
      toks = line.split(args.delimiter)

      try:
        ts = int(toks[0].strip())
      except: # invalid timestamp
        continue

      for tok in toks[1:]:
        if tok.startswith('https://'):
          try:
            urllib.parse.urlparse(tok)
          except ValueError:
            continue

          rv.append(tok)

  return rv

# Detect language in passed HTML
# Return language as string ID
def process_html(html):
  debug(html)
  soup = bs(html, 'html.parser')
  text = soup.get_text()
  debug(text)
  lang = TextBlob(text)
  return lang.detect_language()


# BEGIN EXECUTION
ap = argparse.ArgumentParser(description='Determine languages used at fedi links')
ap.add_argument(nargs='?', type=argparse.FileType('r'), dest='stdin', default=sys.stdin, help='skarf file for URLs to check. Ignores -u if present')
ap.add_argument('-u', '--input-url', nargs='?', dest='url', type=str, help='URL to check')
ap.add_argument('-d', '--delimiter', type=str, default=',', dest='delimiter', help='Input delimiter')
ap.add_argument('-g', '--debug', dest='debug', action='store_true', default=False, help='Enable debug mode, LOTS of output')

args = ap.parse_args()

if sys.stdin.isatty():
  if not args.url:
    print("No stdin and no URL. Quitting")
    exit(1)
  else:
    try:
      html = fetch_url(args.url)
    except RuntimeError as e:
      debug('failed to fetch url:' + args.url)
      exit(1)

    print(process_html(html))

else:
  urls = parse_skarf(args.stdin.read())
  print('Processing ' + str(len(urls)) + ' URLs')
  for url in urls:
    debug(url)
    try:
      html = fetch_url(url)
    except RuntimeError as e:
      debug('failed to fetch url:' + url)
      continue

    print(process_html(html))
