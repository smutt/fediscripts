#!/usr/bin/env python3

# Copyright (C) 2020, Andrew McConachie, andrew@depht.com
# With help from https://matplotlib.org/gallery/lines_bars_and_markers/barchart.html#sphx-glr-gallery-lines-bars-and-markers-barchart-py

import argparse
import collections
import datetime
import json
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import sys

# Put a label on the top of each bar
def autolabel(bars):
  for bar in bars:
    height = bar.get_height()
    ax.annotate(str(height),
                  xy=(bar.get_x() + bar.get_width() / 2, height),
                  xytext=(0, 2),
                  textcoords="offset points",
                  ha='center', va='bottom')

ap = argparse.ArgumentParser(description='Take JSON data on stdin and chart it')
ap.add_argument('-o', '--output-file', default='gen_chart', dest='outfile', type=str, help='Name of output file without file extension')
ap.add_argument('-t', '--threshold', metavar='THRESHOLD', default=0, type=int, dest='threshold', help='Do not include any value less than THRESHOLD')
ap.add_argument('--title', default=None, type=str, dest='title', help='Chart title. Otherwise taken from JSON input')
ap.add_argument('--top', metavar='TOP', default=10, dest='top', type=int, help='Only chart the top TOP values')
args = ap.parse_args()

if sys.stdin.isatty():
  print('No input')
  exit(1)

try:
  stdin_data = json.loads(sys.stdin.read().strip())
except json.JSONDecodeError as e:
  print('gen_chart.py:JSON LoadError:' + str(e))
  exit(1)

# Determine title
if args.title:
  title = args.title
else:
  title = list(stdin_data)[0]

# Prep data and labels
# Build a dict of dicts of parallel lists
sets = collections.OrderedDict()
set_list = []
for k,v in stdin_data.items():
  sets[k] = {}
  set_list.append(k)
  sets[k]['data'] = []
  sets[k]['labels'] = []
  other = 0
  total = 0
  for key,value in v.items():
    if key.lower() == 'total':
      total = value
      continue
    if key.lower() == 'other':
      other += value
      continue
    if value < args.threshold:
      other += value
    else:
      sets[k]['labels'].append(key)
      sets[k]['data'].append(value)

  sets[k]['labels'].append('other')
  sets[k]['data'].append(other)
  print(k + ' labels:' + repr(sets[k]['labels']))
  print(k + ' data:' + repr(sets[k]['data']))

if len(set_list) > 2:
  print('No more than 2 data sets supported')
  exit(1)

# The length of all lists must be the same
ll = len(sets[set_list[0]]['data'])
if ll > args.top:
  ll = args.top
  for k,v, in sets.items():
    v['data'] = v['data'][:args.top]
    v['labels'] = v['labels'][:args.top]

for k,v in sets.items():
  if len(v['data']) != ll or len(v['labels']) != ll:
    print('Bad length of input data')
    exit(1)

x = np.arange(ll)  # the label locations
width = 0.35  # the width of the bars

fig, ax = plt.subplots()
if len(set_list) == 2:
  bar0 = ax.bar(x - width/2, sets[set_list[0]]['data'], width, label=set_list[0])
  bar1 = ax.bar(x + width/2, sets[set_list[1]]['data'], width, label=set_list[1])
else:
  bar = ax.bar(x - width/2, sets[set_list[0]]['data'], width, label=set_list[0])

# Setup labels
ax.set_ylabel('Num Instances')
ax.set_title(title + ' for ' + str(total) + ' instances')
ax.set_xticks(x)
ax.set_xticklabels(sets[set_list[0]]['labels'])
plt.setp(ax.get_xticklabels(), rotation=30, horizontalalignment='right')

# Put numbers at the top of each bar
if len(set_list) == 2:
  autolabel(bar0)
  autolabel(bar1)
else:
  autolabel(bar)

date = datetime.datetime.now().strftime("%Y_%m_%d")
fig.tight_layout()
fig.savefig(args.outfile + '_' + date + '.png')
