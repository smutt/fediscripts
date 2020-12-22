#!/usr/bin/env python3

#  Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import string
import os

###########
# CLASSES #
###########

class FediServer():
  DOMAIN_CHARS = string.ascii_letters + string.digits + '-' + '.' # Valid characters in a DNS name

  def __init__(self, domain, first_seen, last_seen=None, hits=1):
    self.domain = self.confirm_domain(domain.lower().strip())
    self.hits = hits
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
    except:
      print("Error: Bad line in input-file")

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
