# Example: load a config, modify as needed, then save xml
# to run batch experiments, you should write a file like this to generate all configs needed, then call 
# python batchExperiment.py folder_of_config
from common import *
from xml.dom import minidom
import xml.etree.ElementTree as ET
import numpy as np
from copy import deepcopy
import sys

if (len(sys.argv) == 2):
    name = sys.argv[1]
else:
    print_error("you must specify a folder name under configs/")

config_folder = './configs/' + name + '/'
config_filename = config_folder + 'master.xml'
original_config = minidom.parse(config_filename)

index = 0
#cvar_a_vec = np.linspace(0.1,0.9,3)
#cvar_Cu_vec = [0,0.5,1,2,5]
#cvar_a_vec = np.linspace(0.1,0.9,9)
#cvar_Cu_vec = np.linspace(0.1,0.9,9)

# grid 5,6, grid 6 use 0.1 noise, grid5 use 0.2 noise
#cvar_a_vec = [0.99,0.95,0.93]
#cvar_Cu_vec = np.linspace(0.5,0.9,5)

# grid 7, also has hand written tests with different noise level
#cvar_a_vec = [0.95]
#cvar_Cu_vec = [0.5]
#enable_cvar = True
#cvar_A_vec = [2,4,6,8,10]

# grid 9a
enable_cvar = True
cvar_a_vec = np.linspace(0.1,0.9,5)
cvar_A_vec = [4,7,10]
cvar_Cu = 0.5

# grid9b
noise_vec = [0.3,0.5,0.7]

# 15 experiments
for cvar_A in cvar_A_vec:
    for cvar_a in cvar_a_vec:
        config = deepcopy(original_config)

        # get cvar_a,cvar_Cu
        config_cars = config.getElementsByTagName('cars')[0]
        config_car = config_cars.getElementsByTagName('car')[0]
        config_controller = config_car.getElementsByTagName('controller')[0]
        attrs = config_controller.attributes.items()

        config_controller.attributes['enable_cvar'] =  str(enable_cvar)
        config_controller.attributes['cvar_Cu'] =  str(cvar_Cu)
        config_controller.attributes['cvar_a'] =   str(cvar_a)
        config_controller.attributes['cvar_A'] =   str(cvar_A)

        with open(config_folder+'exp%d.xml'%(index),'w') as f:
            config.writexml(f)
        index += 1

for noise in noise_vec:
    for cvar_a in cvar_a_vec:
        config = deepcopy(original_config)
        # get state_noise_std
        config_extensions = config.getElementsByTagName('extensions')[0]
        for config_extension in config_extensions.getElementsByTagName('extension'):
            if config_extension.getAttribute('handle') == 'simulator':
                config_extension.attributes['state_noise_std'] = str([noise]*6)

        # get cvar_a,cvar_Cu
        config_cars = config.getElementsByTagName('cars')[0]
        config_car = config_cars.getElementsByTagName('car')[0]
        config_controller = config_car.getElementsByTagName('controller')[0]
        attrs = config_controller.attributes.items()

        config_controller.attributes['enable_cvar'] =  str(enable_cvar)
        config_controller.attributes['cvar_Cu'] =  str(cvar_Cu)
        config_controller.attributes['cvar_a'] =   str(cvar_a)
        config_controller.attributes['cvar_A'] =   str(cvar_A)
        config_controller.attributes['state_noise_std'] =  str([noise]*6) 

        with open(config_folder+'exp%d.xml'%(index),'w') as f:
            config.writexml(f)
        index += 1



print('generated %d configs'%index)
