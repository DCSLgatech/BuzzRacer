# log experiment parameter for batch experiment
import numpy as np
from common import *
from extension.Extension import Extension
from xml.dom import minidom
import os

class ConfigLogger(Extension):
    def __init__(self,main):
        Extension.__init__(self,main)

    def init(self):
        config = minidom.parse(self.main.config_filename)
        config_extensions = config.getElementsByTagName('extensions')[0]
        for config_extension in config_extensions.getElementsByTagName('extension'):
            if config_extension.getAttribute('handle') == 'simulator':
                self.noise = eval(config_extension.getAttribute('state_noise_magnitude'))[0]

    def postFinal(self):
        # stuff to log down
        entry = []
        # experiment name, this is config folder name (e.g. Cu_a_param_sweep)
        # config file name, (e.g. Cu_a_param_sweep/exp48.xml)
        # log name
        # laps
        # enable_cvar
        # cvar_A
        # cvar_a
        # cvar_Cu
        # laptime_mean
        # laptime_stddev
        # boundary violation
        # obstacle violation
        labels = "experiment name , config file name , log name , laps , cvar_A , cvar_a , cvar_Cu , laptime_mean , laptime_stddev , boundary violation , obstacle violation, noise_type, noise_magnitude "
        entry.append(self.main.experiment_name)
        entry.append(self.main.config_filename)
        entry.append(self.main.logger.logFilename)
        entry.append(self.main.lap_counter.total_laps)

        # retrieve cvar params
        config_filename = self.main.config_filename
        config = minidom.parse(config_filename)
        config_cars = config.getElementsByTagName('cars')[0]
        config_car = config_cars.getElementsByTagName('car')[0]
        config_controller = config_car.getElementsByTagName('controller')[0]
        attrs = config_controller.attributes.items()

        entry.append( config_controller.getAttribute('enable_cvar') )
        entry.append( config_controller.getAttribute('cvar_A') )
        entry.append( config_controller.getAttribute('cvar_a') )
        entry.append( config_controller.getAttribute('cvar_Cu') )

        # these may not be available if watchdog is triggered
        if (not self.main.watchdog.triggered):
            entry.append( self.main.car_laptime_mean[0])
            entry.append( self.main.car_laptime_stddev[0])
            entry.append( self.main.car_total_boundary_violation[0])
            entry.append( self.main.car_total_collisions[0])
        else:
            entry.append(-1 ) 
            entry.append(-1 ) 
            entry.append(-1 ) 
            entry.append(-1 ) 

        entry.append( self.main.simulator.state_noise_type )
        entry.append( self.noise )

        
        log_name = os.path.join(self.main.logger.logFolder,'textlog.txt')
        with open(log_name,'a') as f:
            #f.write(labels)
            #f.write('\n')
            text_entry = [str(item) for item in entry]
            f.write(','.join(text_entry))
            f.write('\n')
        
        
