# analyze debug_dict
import pickle
import matplotlib.pyplot as plt
import numpy as np
import sys
import os
sys.path.append(os.path.abspath('../../src/'))
from common import *

if (len(sys.argv) != 2):
    print_error("Specify a log to load")

filename = sys.argv[1]
with open(filename, 'rb') as f:
    data = pickle.load(f)

target_v = data['target_v']
actual_v = data['actual_v']
throttle = data['throttle']

fig = plt.figure()
ax = fig.gca()
ax.plot(target_v,label="target_v")
ax.plot(actual_v,label="actual_v")
ax.plot(throttle,label="throttle")
ax.legend()
plt.show()
