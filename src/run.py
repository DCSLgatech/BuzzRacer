# universal entry point for running the car
import cv2
from threading import Event,Lock
from time import sleep,time
from math import pi,radians,degrees,asin,acos,isnan
import matplotlib.pyplot as plt

from common import *
from vicon import Vicon
from car import Car
from Track import Track
from RCPTrack import RCPtrack
from skidpad import Skidpad
from Optitrack import Optitrack
from joystick import Joystick

from advCarSim import advCarSim
from kinematicSimulator import kinematicSimulator
from ethCarSim import ethCarSim

from ctrlMpcWrapper import ctrlMpcWrapper
from ctrlStanleyWrapper import ctrlStanleyWrapper
from ctrlMppiWrapper import ctrlMppiWrapper
from ctrlCcmppiWrapper import ctrlCcmppiWrapper

from timeUtil import execution_timer

from enum import Enum, auto

# Extensions
from Laptimer import Laptimer
from CrosstrackErrorTracker import CrosstrackErrorTracker
from Gifsaver import Gifsaver
from Logger import Logger
from LapCounter import LapCounter

# for cpu/ram analysis
#import psutil
class StateUpdateSource(Enum):
    vicon = auto()
    optitrack = auto()
    kinematic_simulator = auto()
    dynamic_simulator = auto()
    eth_simulator = auto()

class VehiclePlatform(Enum):
    offboard = auto()
    onboard = auto() # NOT IMPLEMENTED
    kinematic_simulator = auto()
    # no controller, this means out of loop control
    empty = auto()
    dynamic_simulator = auto()
    eth_simulator = auto()


class Controller(Enum):
    stanley = auto()
    purePursuit = auto() # NOT IMPLEMENTED
    joystick = auto()
    dynamicMpc = auto()
    mppi = auto()
    ccmppi = auto()

    # no controller, this means out of loop control
    empty = auto()


class Main():
    def __init__(self,):
        self.timer = execution_timer(True)
        # state update rate
        self.dt = 0.03

        # noise in simulation
        self.sim_noise = False
        # simulation noise
        self.sim_noise_cov = np.diag([0.1,0.3,0.1,0.3,radians(10),1.0])

        # run the track in reverse direction
        self.reverse = False

        # prepare track object
        #self.track = self.prepareSkidpad()
        # or, use RCP track
        self.track = self.prepareRcpTrack()
        self.visualization_img = None

        # a list of Car class object running
        # the pursuer car
        car0 = self.prepareCar("porsche", StateUpdateSource.kinematic_simulator, VehiclePlatform.kinematic_simulator, Controller.ccmppi,init_state=(3.7*0.6,1.75*0.6, radians(-90)), start_delay=0.0)
        # the escaping car
        car1 = self.prepareCar("porsche_slow", StateUpdateSource.kinematic_simulator, VehiclePlatform.kinematic_simulator, Controller.stanley,init_state=(2.3*0.6,0.7*0.6, radians(90)), start_delay=0.0)

        # to allow car 0 to track car1, predict its future trajectory etc
        car0.opponents = []
        car0.opponents = [car1]
        car0.initTrackOpponents()
        '''
        car1.opponents = []
        car1.initTrackOpponents()
        car2.opponents = []
        car2.initTrackOpponents()
        '''
        #self.cars = [car0]
        self.cars = [car0, car1]
        for i in range(len(self.cars)):
            self.cars[i].id = i

        # real time/sim_time
        # larger value result in slower simulation
        # NOTE ignored in real experiments
        self.real_sim_time_ratio = 1.0
        for car in self.cars:
            if car.stateUpdateSource != StateUpdateSource.kinematic_simulator and car.stateUpdateSource != StateUpdateSource.dynamic_simulator and car.stateUpdateSource != StateUpdateSource.eth_simulator:
                print_warning("real_sim_time ratio override to 1.0 when running on physical platforms")
                self.real_sim_time_ratio = 1.0
                break


        # flag to quit all child threads gracefully
        self.exit_request = Event()
        # if set, continue to follow trajectory but set throttle to -0.1
        # so we don't leave car uncontrolled at max speed
        # currently this is ignored and pressing 'q' the first time will cut motor
        # second 'q' will exit program
        self.slowdown = Event()
        self.slowdown_ts = 0

        # log with undetermined format
        self.debug_dict = []
        for car in self.cars:
            self.debug_dict.append({'target_v':[],'actual_v':[],'throttle':[],'p':[],'i':[],'d':[],'crosstrack_error':[],'heading_error':[]})

        # verify that a valid track subclass is specified
        if not issubclass(type(self.track),Track):
            print_error("specified self.track is not a subclass of Track")

        self.prepareVisualization()


        # --- New approach: Extensions ---
        self.extensions = []
        # Laptimer
        self.extensions.append(Laptimer(self))
        self.extensions.append(CrosstrackErrorTracker(self))
        self.extensions.append(LapCounter(self))
        # save experiment as a gif, this provides an easy to use visualization for presentation
        #self.extensions.append(Gifsaver(self))
        #self.extensions.append(Logger(self))

        for item in self.extensions:
            item.init()

    # run experiment until user press q in visualization window
    def run(self):
        t = self.timer
        print_info("running ... press q to quit")
        while not self.exit_request.isSet():
            t.s()
            self.update()
            # -- Extension update -- 
            for item in self.extensions:
                item.update()
            t.e()
        # exit point
        print_info("Exiting ...")
        cv2.destroyAllWindows()
        for item in self.extensions:
            item.final()
        for car in self.cars:
            car.stopStateUpdate(car)

            if (car.controller == Controller.joystick):
                print_info("exiting joystick... move joystick a little")
                car.joystick.quit()

    def updateVisualization(self,):
        # we want a real-time simulation, waiting sim_dt between each simulation step
        # however, since we cannot update visualization at sim_dt, we need to keep track of how much time has passed in simulation and match visualization accordingly
        # for simplicity we use the simulation time of the first car
        if (self.cars[0].stateUpdateSource == StateUpdateSource.dynamic_simulator \
                or self.cars[0].stateUpdateSource == StateUpdateSource.kinematic_simulator\
                or self.cars[0].stateUpdateSource == StateUpdateSource.eth_simulator):
            if (self.real_sim_dt is None):
                self.real_sim_dt = time()
            time_to_reach = self.cars[0].simulator.t*self.real_sim_time_ratio + self.real_sim_dt
            #print("sim_t = %.3f, time = %.3f, expected= %.3f, delta = %.3f"%(self.cars[0].simulator.t, time()-self.real_sim_dt, self.cars[0].simulator.t*self.real_sim_time_ratio, time_to_reach-time() ))
            if (time_to_reach-time() < 0):
                # DEBUG
                #print_warning("algorithm can't keep up ..... %.3f s"%(time()-time_to_reach))
                pass

            sleep(max(0,time_to_reach - time()))

        # restrict update rate to 0.02s/frame, a rate higher than this can lead to frozen frames
        if (time()-self.visualization_ts>0.02 \
                or self.cars[0].stateUpdateSource == StateUpdateSource.dynamic_simulator \
                or self.cars[0].stateUpdateSource == StateUpdateSource.kinematic_simulator\
                or self.cars[0].stateUpdateSource == StateUpdateSource.eth_simulator):
            img = self.img_track.copy()
            for car in self.cars:
                img = self.track.drawCar(img, car.state, car.steering)

                # plot reference trajectory following optimal control sequence
                if (car.controller == Controller.mppi):
                    x_ref = self.debug_dict[car.id]['x_ref']
                    for coord in x_ref:
                        x,y = coord
                        img = self.track.drawPoint(img,(x,y),color=(255,0,0))

                # CCMPPI
                if (car.controller == Controller.ccmppi):

                    # plot sampled trajectory (if car follow one sampled control traj)
                    coords_vec = self.debug_dict[car.id]['rollout_traj_vec']
                    for coords in coords_vec:
                        img = self.track.drawPolyline(coords,lineColor=(200,200,200),img=img)

                    # plot ideal trajectory (if car follow synthesized control)
                    coords = self.debug_dict[car.id]['ideal_traj']
                    for coord in coords:
                        x,y = coord
                        img = self.track.drawPoint(img,(x,y),color=(255,0,0))
                    img = self.track.drawPolyline(coords,lineColor=(100,0,100),img=img)

                    # plot opponent prediction
                    '''
                    coords_vec = self.debug_dict[car.id]['opponent_prediction']
                    for coords in coords_vec:
                        for coord in coords:
                            x,y = coord
                            img = self.track.drawPoint(img,(x,y),color=(255,0,0))
                        img = self.track.drawPolyline(coords,lineColor=(100,0,0),img=img)
                    '''

                    '''
                    coords_vec = np.array(coords_vec)
                    for i in range(len(coords_vec)):
                        plt.plot(coords_vec[0,:,0], coords_vec[0,:,1])
                    plt.show()
                    '''

            # TODO 
            '''
            if 'opponent' in self.debug_dict[0]:
                x_ref = self.debug_dict[0]['opponent']
                for coord in x_ref[0]:
                    x,y = coord
                    img = self.track.drawPoint(img,(x,y),color=(255,0,0))
            '''

            # plot reference trajectory following some alternative control sequence
            '''
            x_ref_alt = self.debug_dict[0]['x_ref_alt']
            for samples in x_ref_alt:
                for coord in samples:
                    x,y = coord
                    img = self.track.drawPoint(img,(x,y),color=(100,0,0))
            '''

            self.visualization_ts = time()

            self.visualization_img = img
            cv2.imshow('experiment',img)

            '''
            # hardware resource usage
            ram = psutil.virtual_memory().percent
            cpu = psutil.cpu_percent()
            print("ram = %.2f, cpu = %.2f"%(ram,cpu))
            '''

            k = cv2.waitKey(1) & 0xFF
            if k == ord('q'):
                # first time q is presed, slow down
                if not self.slowdown.isSet():
                    print("slowing down, press q again to shutdown")
                    self.slowdown.set()
                    self.slowdown_ts = time()
                else:
                    # second time, shut down
                    self.exit_request.set()

    # run the control/visualization update
    # this should be called in a loop(while not self.exit_request.isSet()) continuously, without delay

    # in simulation, this is called with evenly spaced time
    # in real experiment, this is called after a new vicon update is pulled
    # when a new vicon/optitrack state is available, vi.newState.isSet() will be true
    # client (this function) need to unset that event
    def update(self,):
        for i in range(len(self.cars)):
            car = self.cars[i]
            # wait on next state update
            car.new_state_update.wait()
            # manually clear the Event()
            car.new_state_update.clear()
            # retrieve car state from visual tracking update
            car.updateState(car)
            #print("car %d T: %.2f S: %.2f, y pos %.2f"%(i,car.throttle, car.steering, car.state[1]))

            # force motor freeze if start_delay has not been reached
            if (self.cars[i].stateUpdateSource == StateUpdateSource.dynamic_simulator \
                    or self.cars[i].stateUpdateSource == StateUpdateSource.kinematic_simulator \
                    or self.cars[i].stateUpdateSource == StateUpdateSource.eth_simulator):
                if (car.simulator.t < car.start_delay):
                    car.steering = 0
                    car.throttle = 0
                    continue
            else:
                if (time() < car.start_delay):
                    car.steering = 0
                    car.throttle = 0
                    continue


            # apply controller
            # states:(x,y,theta,vforward,vsideway=0,omega)
            if (car.controller == Controller.stanley):
                throttle,steering,valid,debug_dict = car.ctrlCar(car.state,car.track,reverse=self.reverse)
            elif (car.controller == Controller.dynamicMpc):
                throttle,steering,valid,debug_dict = car.ctrlCar(car.state,car.track,reverse=self.reverse)
            elif (car.controller == Controller.joystick):
                throttle = car.joystick.throttle
                # just use right side for both ends
                steering = car.joystick.steering*car.max_steering_right
                valid = True
            elif (car.controller == Controller.mppi):
                throttle,steering,valid,debug_dict = car.ctrlCar(car.state,car.track,reverse=self.reverse)
            elif (car.controller == Controller.ccmppi):
                throttle,steering,valid,debug_dict = car.ctrlCar(car.state,car.track,reverse=self.reverse)
            elif (car.controller == Controller.empty):
                throttle = 0
                steering = 0
                valid = True

            # post processing
            if not valid:
                print_warning("ctrlCar invalid retval")
                exit(1)
            self.debug_dict[i].update(debug_dict)
            if isnan(steering):
                print("error steering nan")
            #print("T= %4.1f, S= %4.1f (deg)"%( throttle,degrees(steering)))

            if self.slowdown.isSet():
                throttle = 0.0
            
            #print("V = %.2f"%(car.state[3]))
            car.steering = steering
            # NOTE this may affect model prediction
            car.throttle = min(throttle, car.max_throttle)

            if (car.vehiclePlatform == VehiclePlatform.offboard):
                car.actuate(steering,throttle)
                print(car.steering, car.throttle)
                # TODO implement throttle model
                # do not use EKF for now
                #car.vi.updateAction(car.steering, car.getExpectedAcc())
            elif (car.vehiclePlatform == VehiclePlatform.kinematic_simulator):
                # update is done in updateSimulation()
                pass
            elif (car.vehiclePlatform == VehiclePlatform.dynamic_simulator):
                # update is done in updateSimulation()
                pass
            elif (car.vehiclePlatform == VehiclePlatform.eth_simulator):
                # update is done in updateSimulation()
                pass
            elif (car.vehiclePlatform == VehiclePlatform.onboard):
                raise NotImplementedError

        self.updateVisualization()
        
# ---- Short Routine ----

    def prepareVisualization(self,):
        self.visualization_ts = time()
        self.img_track = self.track.drawTrack()
        self.img_track = self.track.drawRaceline(img=self.img_track)
        cv2.imshow('experiment',self.img_track)
        cv2.waitKey(1)

    def prepareSkidpad(self,):
        sp = Skidpad()
        sp.initSkidpad(radius=2,velocity=target_velocity)
        return sp

    def prepareRcpTrackSmall(self,):
        # current track setup in mk103, L shaped
        # width 0.563, length 0.6
        mk103 = RCPtrack()
        mk103.initTrack('uuruurddddll',(5,3),scale=0.57)
        # add manual offset for each control points
        adjustment = [0,0,0,0,0,0,0,0,0,0,0,0]
        adjustment[4] = -0.5
        adjustment[8] = -0.5
        adjustment[9] = 0
        adjustment[10] = -0.5
        mk103.initRaceline((2,2),'d',4,offset=adjustment)
        return mk103

    def prepareRcpTrack(self,):
        # width 0.563, square tile side length 0.6

        # full RCP track
        # NOTE load track instead of re-constructing
        fulltrack = RCPtrack()
        fulltrack.startPos = (0.6*3.5,0.6*1.75)
        fulltrack.startDir = radians(90)
        fulltrack.load()
        return fulltrack

        # row, col
        track_size = (6,4)
        #fulltrack.initTrack('uuurrullurrrdddddluulddl',track_size, scale=0.565)
        fulltrack.initTrack('uuurrullurrrdddddluulddl',track_size, scale=0.6)
        # add manual offset for each control points
        adjustment = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]

        adjustment[0] = -0.2
        adjustment[1] = -0.2
        #bottom right turn
        adjustment[2] = -0.2
        adjustment[3] = 0.5
        adjustment[4] = -0.2

        #bottom middle turn
        adjustment[6] = -0.2

        #bottom left turn
        adjustment[9] = -0.2

        # left L turn
        adjustment[12] = 0.5
        adjustment[13] = 0.5

        adjustment[15] = -0.5
        adjustment[16] = 0.5
        adjustment[18] = 0.5

        adjustment[21] = 0.35
        adjustment[22] = 0.35

        # start coord, direction, sequence number of origin
        # pick a grid as the starting grid, this doesn't matter much, however a starting grid in the middle of a long straight helps
        # to find sequence number of origin, start from the start coord(seq no = 0), and follow the track, each time you encounter a new grid it's seq no is 1+previous seq no. If origin is one step away in the forward direction from start coord, it has seq no = 1
        fulltrack.initRaceline((3,3),'d',10,offset=adjustment)
        return fulltrack

    # generate a Car instance with appropriate setting
    # config_name: "porsche" or "lambo"
    # state_update_source StateUpdateSource.xx
    # platform: VehiclePlatform.xx
    # controller: Controller.xx
    # start_delay: time delay at start, positive delay means car remains still  until delay(sec) has passed 
    def prepareCar(self,config_name, state_update_source, platform, controller,init_state, start_delay=0.0):
        porsche_setting = {'wheelbase':90e-3,
                         'max_steer_angle_left':radians(27.1),
                         'max_steer_pwm_left':1150,
                         'max_steer_angle_right':radians(27.1),
                         'max_steer_pwm_right':1850,
                         'serial_port' : '/dev/ttyUSB0',
                         'optitrack_streaming_id' : 2,
                         'max_throttle' : 0.7}

        lambo_setting = {'wheelbase':98e-3,
                         'max_steer_angle_left':asin(2*98e-3/0.52),
                         'max_steer_pwm_left':1100,
                         'max_steer_angle_right':asin(2*98e-3/0.47),
                         'max_steer_pwm_right':1850,
                         'serial_port' : '/dev/ttyUSB1',
                         'optitrack_streaming_id' : 15,
                         'max_throttle' : 0.5}


        if config_name == "porsche":
            car_setting = porsche_setting
        elif config_name == "porsche_slow":
            car_setting = porsche_setting
            car_setting['max_throttle'] = 0.7
        elif config_name == "lambo":
            car_setting = lambo_setting
        else:
            print_error("Unrecognized car config")

        if (state_update_source == StateUpdateSource.kinematic_simulator):
            car_setting['serial_port'] = None
            #car_setting['max_throttle'] = 1.0
            #print_warning("Limiting max_throttle to %.2f"%car_setting['max_throttle'])
        elif (state_update_source == StateUpdateSource.dynamic_simulator):
            car_setting['serial_port'] = None
            #car_setting['max_throttle'] = 1.0
            #print_warning("Limiting max_throttle to %.2f"%car_setting['max_throttle'])
        elif (state_update_source == StateUpdateSource.eth_simulator):
            car_setting['serial_port'] = None
            #car_setting['max_throttle'] = 1.0
            #print_warning("Limiting max_throttle to %.2f"%car_setting['max_throttle'])

        # select right controller subclass to instantiate for car
        if (controller == Controller.dynamicMpc):
            car = ctrlMpcWrapper(car_setting,self.dt)
        elif (controller == Controller.stanley):
            car = ctrlStanleyWrapper(car_setting,self.dt)
        elif (controller == Controller.mppi):
            car = ctrlMppiWrapper(car_setting,self.dt)
        elif (controller == Controller.ccmppi):
            car = ctrlCcmppiWrapper(car_setting,self.dt)

        car.stateUpdateSource = state_update_source
        car.vehiclePlatform = platform
        car.controller = controller
        car.start_delay = start_delay

        if (car.controller == Controller.joystick):
            car.joystick = Joystick()
        if car.stateUpdateSource == StateUpdateSource.optitrack:
            car.initStateUpdate = self.initOptitrack
            car.updateState = self.updateOptitrack
            car.stopStateUpdate = self.stopOptitrack
        elif car.stateUpdateSource == StateUpdateSource.vicon:
            print_error("vicon not implemented")
            car.initStateUpdate = self.initVicon
            car.updateState = self.updateVicon
            car.stopStateUpdate = self.stopVicon
        elif car.stateUpdateSource == StateUpdateSource.kinematic_simulator:
            car.initStateUpdate = self.initKinematicSimulation
            car.updateState = self.updateKinematicSimulation
            car.stopStateUpdate = self.stopKinematicSimulation
        elif car.stateUpdateSource == StateUpdateSource.dynamic_simulator:
            car.initStateUpdate = self.initDynamicSimulation
            car.updateState = self.updateDynamicSimulation
            car.stopStateUpdate = self.stopDynamicSimulation
        elif car.stateUpdateSource == StateUpdateSource.eth_simulator:
            car.initStateUpdate = self.initEthSimulation
            car.updateState = self.updateEthSimulation
            car.stopStateUpdate = self.stopEthSimulation
        else:
            print_error("unknown state update source")

        # NOTE this syntax only work on simulator
        car.initStateUpdate(car,init_state)

        if (car.controller == Controller.dynamicMpc):
            if (car.stateUpdateSource == StateUpdateSource.dynamic_simulator):
                car.initMpcSim(car.simulator)
            elif (car.stateUpdateSource == StateUpdateSource.optitrack):
                car.initMpcReal()
        elif (car.controller == Controller.mppi or car.controller == Controller.ccmppi):
            if (car.stateUpdateSource == StateUpdateSource.dynamic_simulator \
                    or car.stateUpdateSource == StateUpdateSource.eth_simulator \
                    or car.stateUpdateSource == StateUpdateSource.kinematic_simulator):
                car.init(self.track,car.simulator)
            elif (car.stateUpdateSource == StateUpdateSource.optitrack):
                car.init(self.track)
        # NOTE we can turn on/off laptimer for each car individually
        car.enableLaptimer = True
        # so that Car class has access to the track
        car.track = self.track
        return car


    # call before exiting
    def stop(self,):
        for car in self.cars:
            car.stopStateUpdate(car)


# ---- VICON ----
# NOTE outdated
    def initVicon(self,):
        print_info("Initializing Vicon...")
        self.vi = Vicon()
        self.new_state_update = self.vi.newState
        self.vicon_dt = 0.01
        # wait for vicon to find objects
        sleep(0.05)
        self.car.vicon_id = self.vi.getItemID('nick_mr03_porsche')
        if car.vicon_id is None:
            print_error("error, can't find car in vicon")
            exit(1)
        return

    # update local state
    # TODO use new KF
    # OBSOLETE
    def updateVicon(self,):
        # retrieve vehicle state
        retval = self.vi.getState2d(car.vicon_id)
        if retval is None:
            return
        (x,y,heading) = retval
        kf_x,vx,ax,kf_y,vy,ay,kf_heading,omega = self.vi.getKFstate(self.car.vicon_id)

        # state_car = (x,y,heading, vf, vs, omega)
        # assume no lateral velocity
        vf = (vx**2+vy**2)**0.5

        # low pass filter on vf
        vf_lf, z_vf = signal.lfilter(b,a,[vf],zi=z_vf)
        vf = vf_lf[0]

        self.car_state = (x,y,vf,heading,omega)
        return

    def stopVicon(self,):
        self.vi.stopUpdateDaemon()

# ---- Optitrack ----
    def initOptitrack(self,car,unused=None):
        print_info("Initializing Optitrack...")
        car.vi = Optitrack(wheelbase=car.wheelbase)
        # TODO use acutal optitrack id for car
        # porsche: 2
        car.internal_id = car.vi.getInternalId(car.optitrack_id)
        car.new_state_update = car.vi.newState

    def updateOptitrack(self,car):
        # update for eachj car
        # not using kf state for now
        (x,y,v,theta,omega) = car.vi.getKFstate(car.internal_id)

        #(x,y,theta) = self.vi.getState2d(self.car.internal_id)
        # (x,y,theta,vforward,vsideway=0,omega)
        car.state = (x,y,theta,v,0,omega)
        return

    def stopOptitrack(self,car):
        # the optitrack destructor should handle things properly
        car.vi.quit()
        pass

# ---- Simulation ----
    def initKinematicSimulation(self, car, init_state = (0.3*0.6,1.7*0.6,radians(-90))):
        print_info("kinematic simulation init")
        car.new_state_update = Event()
        car.new_state_update.set()
        self.real_sim_dt = None

        x,y,heading = init_state
        omega = 0

        # NOTE DEBUG
        v = 1.0
        car.simulator = kinematicSimulator( x,y,v,heading)

        car.steering = steering = 0
        car.throttle = throttle = 0
        car.v_target = 0

        car.state = (x,y,heading,v,0,omega)
        car.sim_states = {'coord':(x,y),'heading':heading,'vf':v,'vs':0,'omega':0}
        self.sim_dt = self.dt

    def updateKinematicSimulation(self,car):
        # update car
        sim_states = car.sim_states = car.simulator.updateCar(self.sim_dt,car.throttle,car.steering)
        car.state = np.array([sim_states['coord'][0],sim_states['coord'][1],sim_states['heading'],sim_states['vf'],0,sim_states['omega']])
        car.new_state_update.set()
        if isnan(sim_states['heading']):
            print("error")
        car.new_state_update.set()

    def stopKinematicSimulation(self,car):
        return

# dynamic simulator
    def initDynamicSimulation(self,car,init_state = (0.3*0.6,1.7*0.6,radians(90))):
        car.new_state_update = Event()
        car.new_state_update.set()
        
        x,y,heading = init_state
        car.simulator = advCarSim(x,y,heading,self.sim_noise,self.sim_noise_cov)
        # for keep track of time difference between simulation and reality
        # this allows a real-time simulation
        # here we only instantiate the variable, the actual value will be assigned in updateVisualization, since it takes quite a while to initialize the rest of the program
        self.real_sim_dt = None

        car.steering = steering = 0
        car.throttle = throttle = 0

        car.state = (x,y,heading,0,0,0)
        car.sim_states = {'coord':(x,y),'heading':heading,'vf':throttle,'vs':0,'omega':0}
        self.sim_dt = self.dt

    def updateDynamicSimulation(self,car):
        # update car
        sim_states = car.sim_states = car.simulator.updateCar(self.sim_dt,car.sim_states,car.throttle,car.steering)
        # (x,y,theta,vforward,vsideway=0,omega)
        car.state = np.array([sim_states['coord'][0],sim_states['coord'][1],sim_states['heading'],sim_states['vf'],sim_states['vs'],sim_states['omega']])
        if isnan(sim_states['heading']):
            print("error")
        #print(car.state)
        #print("v = %.2f"%(sim_states['vf']))
        car.new_state_update.set()

    def stopDynamicSimulation(self,car):
        return

# eth dynamic simulator
    def initEthSimulation(self,car,init_state = (0.3*0.6,1.7*0.6,radians(90))):
        car.new_state_update = Event()
        car.new_state_update.set()
        
        x,y,heading = init_state
        car.simulator = ethCarSim(x,y,heading,self.sim_noise,self.sim_noise_cov)
        # for keep track of time difference between simulation and reality
        # this allows a real-time simulation
        # here we only instantiate the variable, the actual value will be assigned in updateVisualization, since it takes quite a while to initialize the rest of the program
        self.real_sim_dt = None

        car.steering = steering = 0
        car.throttle = throttle = 0

        car.state = (x,y,heading,0,0,0)
        car.sim_states = {'coord':(x,y),'heading':heading,'vf':throttle,'vs':0,'omega':0}
        self.sim_dt = self.dt

    def updateEthSimulation(self,car):
        # update car
        sim_states = car.sim_states = car.simulator.updateCar(self.sim_dt,car.sim_states,car.throttle,car.steering)
        # (x,y,theta,vforward,vsideway=0,omega)
        car.state = np.array([sim_states['coord'][0],sim_states['coord'][1],sim_states['heading'],sim_states['vf'],sim_states['vs'],sim_states['omega']])
        if isnan(sim_states['heading']):
            print("error")
        #print(car.state)
        #print("v = %.2f"%(sim_states['vf']))
        car.new_state_update.set()

    def stopEthSimulation(self,car):
        return



if __name__ == '__main__':
    experiment = Main()
    experiment.run()
    print_info("program complete")

    experiment.timer.summary()
    experiment.cars[0].p.summary()


