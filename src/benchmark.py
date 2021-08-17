# universal entry point for running the car
from common import *
from threading import Event,Lock
from math import pi,radians,degrees


from KinematicSimulator import KinematicSimulator

from timeUtil import execution_timer
from TrackFactory import TrackFactory

from Car import Car
from StanleyCarController import StanleyCarController
from CcmppiCarController import CcmppiCarController

# Extensions
from Laptimer import Laptimer
from CrosstrackErrorTracker import CrosstrackErrorTracker
from Gifsaver import Gifsaver
from Logger import Logger
from LapCounter import LapCounter
from CollisionChecker import CollisionChecker
from Optitrack import Optitrack
from Visualization import Visualization
from PerformanceTracker import PerformanceTracker

class Main():
    def __init__(self,params={}):
        self.timer = execution_timer(True)
        # state update rate
        self.dt = 0.02
        self.params = params

        self.track = TrackFactory(name='full')

        #car0 = Car.Factory(self, "porsche", controller=StanleyCarController,init_states=(3.7*0.6,1.75*0.6, radians(-90), 1.0))
        Car.reset()
        car0 = Car.Factory(self, "porsche", controller=CcmppiCarController,init_states=(3.7*0.6,1.75*0.6, radians(-90),2.0))

        self.cars = Car.cars
        print_info("[main] total cars: %d"%(len(self.cars)))

        # flag to quit all child threads gracefully
        self.exit_request = Event()
        # if set, continue to follow trajectory but set throttle to -0.1
        # so we don't leave car uncontrolled at max speed
        # currently this is ignored and pressing 'q' the first time will cut motor
        # second 'q' will exit program
        self.slowdown = Event()
        self.slowdown_ts = 0

        # --- Extensions ---
        self.extensions = []
        # named extensions
        self.visualization = Visualization(self)
        self.extensions.append(self.visualization)
        self.simulator = KinematicSimulator(self)
        self.simulator.match_real_time = False
        self.collision_checker = CollisionChecker(self)
        # Laptimer
        self.extensions.append(Laptimer(self))
        #self.extensions.append(CrosstrackErrorTracker(self))
        self.extensions.append(LapCounter(self))
        # save experiment as a gif, this provides an easy to use visualization for presentation
        #self.extensions.append(Logger(self))
        self.extensions.append(self.collision_checker)

        #self.extensions.append(Optitrack(self))
        self.extensions.append(self.simulator)
        #self.extensions.append(Gifsaver(self))
        self.performance_tracker = PerformanceTracker(self)
        self.extensions.append(self.performance_tracker)

        for item in self.extensions:
            item.init()

        for car in self.cars:
            car.init()

    # run experiment until user press q in visualization window
    def run(self):
        t = self.timer
        print_info("running ... press q to quit")
        while not self.exit_request.isSet():
            t.s()
            self.update()
            t.e()
        # exit point
        print_info("Exiting ...")
        for item in self.extensions:
            item.final()


    # run the control/visualization update
    # this should be called in a loop(while not self.exit_request.isSet()) continuously, without delay

    # in simulation, this is called with evenly spaced time
    # in real experiment, this is called after a new vicon update is pulled
    # when a new vicon/optitrack state is available, vi.newState.isSet() will be true
    # client (this function) need to unset that event
    def update(self,):
        # -- Extension update -- 
        for item in self.extensions:
            item.preUpdate()

        self.new_state_update.wait()
        self.new_state_update.clear()

        for car in self.cars:
            # call controller, send command to car in real experiment
            car.control()

        # -- Extension update -- 
        for item in self.extensions:
            item.update()
        for item in self.extensions:
            item.postUpdate()
        

    # call before exiting
    def stop(self,):
        for car in self.cars:
            car.stopStateUpdate(car)


if __name__ == '__main__':
    log_filename = "log.txt"
    with open(log_filename,'a') as f:
        f.write("# algorithm, samples, car_total_laps, laptime_mean(s),  collision_count, mean_control_effort\n")
    
    experiment_count = 0
    for use_cc in [False, True]:
        for samples in [4096, 2048, 1024, 512, 256, 128]:
            algorithm_text = 'ccmppi' if use_cc else 'mppi'
            params = {'samples':samples, 'use_cc':use_cc}
            experiment_count += 1

            print_info("-------------- start one experiment ------------")
            print_info("experiment no.%d, algorithm: %s, samples: %d"%(experiment_count, algorithm_text, samples))
            experiment = Main(params)
            experiment.run()

            laptime = experiment.car_laptime_mean[0]
            laps = experiment.car_total_laps[0]
            collisions = experiment.car_total_collisions[0]
            control_effort = experiment.performance_tracker.mean_control_effort
            print_info("%s, %d, %d, %.4f, %d, %.5f"%( algorithm_text, samples, laps, laptime, collisions,control_effort))
            with open(log_filename,'a') as f:
                f.write("%s, %d, %d, %.4f, %d, %.5f\n"%( algorithm_text, samples, laps, laptime, collisions,control_effort))
            print_info("-------------- finish one experiment ------------")

    print_info("program complete")
