#!/usr/bin/env python3
# Copyright (C) 2020, Andrew McConachie, <andrew@depht.com>

import urllib.request as req
from html.parser import HTMLParser

# This code is disgusting but it works
class IANAParser(HTMLParser):
  def __init__(self):
    super().__init__()
    self.tlds = {}
    self.last_tld = ''

  def handle_starttag(self, tag, attrs):
    if tag == 'a':
      if attrs[0][0] == 'href' and attrs[0][1].startswith('/domains/root/db/'):
        self.last_tld = attrs[0][1].split('.html')[0].split('/')[-1]

  def handle_data(self, data):
    if len(self.last_tld) > 0:
      if data in ['country-code', 'infrastructure', 'generic', 'generic-restricted', 'sponsored', 'test']:
        self.tlds[self.last_tld] = data
        self.last_tld = ''


# BEGIN EXECUTION
html = str(req.urlopen('https://www.iana.org/domains/root/db').read())
parser = IANAParser()
parser.feed(html)

print("#TLD,TYPE")
for label,tld_type in parser.tlds.items():
  print(label + "," + tld_type)
