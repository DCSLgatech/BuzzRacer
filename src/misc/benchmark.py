# universal entry point for running the car
import argparse
from common import *
from threading import Event,Lock
from math import pi,radians,degrees


from KinematicSimulator import KinematicSimulator
from DynamicSimulator import DynamicSimulator

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
from Watchdog import Watchdog

class Main():
    def __init__(self,params={}):
        self.timer = execution_timer(True)
        # state update rate
        self.dt = 0.03
        self.params = params

        self.track = TrackFactory(name='full')

        self.simulator = DynamicSimulator(self)
        #car0 = Car.Factory(self, "porsche", controller=StanleyCarController,init_states=(3.7*0.6,1.75*0.6, radians(-90), 1.0))
        Car.reset()
        car0 = Car.Factory(self, "porsche", controller=CcmppiCarController,init_states=(3.7*0.6,1.75*0.6, radians(-90),1.0))

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
        self.simulator.match_real_time = False
        self.collision_checker = CollisionChecker(self)
        # Laptimer
        self.laptimer = Laptimer(self)
        self.extensions.append(self.laptimer)
        #self.extensions.append(CrosstrackErrorTracker(self))
        self.extensions.append(LapCounter(self))
        # save experiment as a gif, this provides an easy to use visualization for presentation
        self.logger = Logger(self)
        self.extensions.append(self.logger)
        self.extensions.append(self.collision_checker)

        #self.extensions.append(Optitrack(self))
        self.extensions.append(self.simulator)
        self.gifsaver = Gifsaver(self)
        self.extensions.append(self.gifsaver)
        self.performance_tracker = PerformanceTracker(self)
        self.extensions.append(self.performance_tracker)
        self.watchdog = Watchdog(self)
        self.extensions.append(self.watchdog)

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
            item.preFinal()
        for item in self.extensions:
            item.final()
        for item in self.extensions:
            item.postFinal()


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
    # start with no. skip experiment, index start with 0
    # e.g. skip = 3 means skip 0,1,2
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip", help="number of experiments to skip", type=int, default=0)
    args = parser.parse_args()
    print_info("skipping %d experiments"%(args.skip))

    log_filename = "log.txt"
    '''
    with open(log_filename,'a') as f:
        f.write("# algorithm, samples, car_total_laps, laptime_mean(s),  collision_count, mean_control_effort, terminal_cov(position), laptime_stddev, log_no\n")
    '''
    
    experiment_count = 0
    # 3*60 = 180 : 789min
    #old_alfas = np.hstack([np.linspace(0.5,1.0,6)])
    #old_betas = np.hstack([np.linspace(1,10,10)])
    old_alfas = []
    old_betas = []
    alfas = np.hstack([np.linspace(0.5,0.9,9)])
    betas = np.hstack([np.linspace(1,6,11)])
    #alfas = np.hstack([np.linspace(0.7,0.9,2)])
    #betas = np.hstack([np.linspace(50,150,3)])

    #for algorithm in ['mppi-same-injected','mppi-same-terminal-cov','ccmppi']:
    #for algorithm in ['mppi-same-injected']:
    for i in range(10):
        for alfa in alfas:
            for beta in betas:
                if (alfa in old_alfas and beta in old_betas):
                    continue
                #for algorithm in ['mppi-same-injected','ccmppi']:
                for algorithm in ['ccmppi']:
                    samples = 4096
                    params = {'samples':samples, 'algorithm':algorithm,'alfa':alfa,'beta':beta}

                    experiment_count += 1
                    if (experiment_count < args.skip):
                        continue

                    print_info("-------------- start one experiment ------------")
                    print_info("experiment no.%d, algorithm: %s, samples: %d"%(experiment_count, algorithm, samples))
                    experiment = Main(params)
                    experiment.run()

                    try:
                        laptime = experiment.car_laptime_mean[0]
                        laps = experiment.car_total_laps[0]
                        laptime_stddev = experiment.car_laptime_stddev[0]
                        collisions = experiment.car_total_collisions[0]
                        control_effort = experiment.performance_tracker.mean_control_effort
                        terminal_cov = experiment.performance_tracker.terminal_cov
                    except (IndexError,AttributeError,IndexError) as e:
                        laptime = -1
                        laps = -1
                        laptime_stddev = -1
                        collisions = -1
                        control_effort = -1
                        terminal_cov = -1
                        print_warning(" bad experiment "+str(e))
                    text = "%25s, %d, %d, %.4f, %d, %.5f, %.5f, %.5f, %d, %s, %.2f, %.2f"%( algorithm, samples, laps, laptime, collisions,control_effort, terminal_cov, laptime_stddev, experiment.logger.log_no, str(experiment.watchdog.triggered),alfa,beta)
                    print_info(text)
                    with open(log_filename,'a') as f:
                        f.write(text +"\n")
                    print_info("-------------- finish one experiment ------------")

    print_info("program complete")
    exit(0)
