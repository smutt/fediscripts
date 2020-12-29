#!/usr/bin/env python3

# Copyright (C) 2020, Andrew McConachie, andrew@depht.com
# With help from https://matplotlib.org/gallery/lines_bars_and_markers/barchart.html#sphx-glr-gallery-lines-bars-and-markers-barchart-py

import argparse
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

ap = argparse.ArgumentParser(description='Take single JSON dict on stdin and chart it')
ap.add_argument('-o', '--output-file', default='gen_bar', dest='outfile', type=str, help='Name of output file without file extension')
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
  print('gen_bar.py:JSON LoadError:' + str(e))
  exit(1)

print(repr(stdin_data))

if len(stdin_data) > 1:
  print('No more than 1 data set supported')
  exit(1)

# Determine title
top_key = list(stdin_data)[0]
if args.title:
  title = args.title
else:
  title = top_key

# Prep data and labels
data = []
labels = []
other = 0
total = 0
for key,value in stdin_data[top_key].items():
  if key.lower() == 'total':
    total = value
    continue
  if key.lower() == 'other':
    other += value
    continue
  if value < args.threshold:
    other += value
  else:
    labels.append(key)
    data.append(value)

if other:
  labels.append('other')
  data.append(other)

print('labels:' + repr(labels))
print('data:' + repr(data))

# The length of all lists must be the same
if len(data) != len(labels):
  print('Bad length of input data')
  exit(1)

x = np.arange(len(labels))  # the label locations
width = 0.35  # the width of the bars

fig, ax = plt.subplots()
bar = ax.bar(x, data, width, label=title)

# Setup labels
ax.set_ylabel('Num Instances')
ax.set_title(title + ' for ' + str(total) + ' instances')
ax.set_xticks(x)
ax.set_xticklabels(labels)
plt.setp(ax.get_xticklabels(), rotation=30, horizontalalignment='right')

# Put numbers at the top of each bar
autolabel(bar)

date = datetime.datetime.now().strftime("%Y_%m_%d")
fig.tight_layout()
fig.savefig(args.outfile + '_' + date + '.png')
