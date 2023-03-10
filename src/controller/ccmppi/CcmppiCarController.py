# CCMPPI controller wrapper with kinematic bicycle model
import os
import sys
base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), './ccmppi/')
sys.path.append(base_dir)

import cv2
import numpy as np
from time import time,sleep
import matplotlib.pyplot as plt
from scipy.interpolate import splprep, splev,CubicSpline,interp1d
from math import atan2,radians,degrees,sin,cos,pi,tan,copysign,asin,acos,isnan,exp,pi,atan
import random

from common import *
from util.timeUtil import execution_timer
from controller.ccmppi.ccmppi import CCMPPI
from CarController import CarController
from extension.simulator.KinematicSimulator import KinematicSimulator
from extension.simulator.DynamicSimulator import DynamicSimulator
import pickle

class CcmppiCarController(CarController):
    def __init__(self,car,config):
        # default parameters
        # diagnal terms of control cost matrix u'Ru
        self.R_diag = [0.01, 0.01]
        # control effort u'Ru
        self.utru = 0
        # load parameters
        super().__init__(car,config)


        self.car = car
        self.track = self.car.main.track
        self.debug_dict = {}
        np.set_printoptions(formatter={'float': lambda x: "{0:7.4f}".format(x)})

        # given parameterized raceline x,y = R(s), this corresponds to raceline_s
        # last_s is the last s such that R(last_s) is closest to vehicle
        # used as a starting point for root finding
        self.last_s = None
        self.p = execution_timer(True)

        self.opponents = []
        self.opponent_prediction = []

        # DEBUG
        self.terminal_cov_vec = []
        self.plotDebugFlag = True
        self.getEstimatedTerminalCovFlag = False

        '''
        # set config items
        for key,value_text in config.attributes.items():
            try:
                value = eval(value_text)
            except NameError:
                value = value_text
            setattr(self,key,value)
            #self.print_info(" controller.",key,'=',value_text)
        '''



    # if running on real platform, set sim to None so that default values for car dimension/properties will be used
    def init(self):
        car = self.car
        self.model = type(car.main.simulator)
        self.wheelbase = car.wheelbase
        self.ccmppi_dt = car.main.dt
        algorithm = self.algorithm

        if (algorithm == 'ccmppi'):
            self.noise_cov = np.diag([(self.car.max_throttle)**2,radians(20.0)**2])
            cc_ratio = 0.8
        elif (algorithm == 'mppi-same-injected'):
            ratio = 1.0
            self.noise_cov = np.diag([(self.car.max_throttle*ratio)**2,radians(20.0*ratio)**2])
            cc_ratio = 0.0
        elif (algorithm == 'mppi-same-terminal-cov'):
            ratio = 0.4
            self.noise_cov = np.diag([(self.car.max_throttle*ratio)**2,radians(20.0*ratio)**2])
            cc_ratio = 0.0
        self.print_info(algorithm)
        self.print_info(" injected noise" + str(self.noise_cov))

        self.track = self.car.main.track
        self.discretized_raceline_len = 1024
        # control noise for MPPI exploration
        self.control_limit = np.array([[-self.car.max_throttle,self.car.max_throttle],[-radians(27.1),radians(27.1)]])


        # discretize raceline for use in MPPI
        self.prepareDiscretizedRaceline()
        try:
            cc_ratio = self.cc_ratio
            self.print_info('overriding cc_ratio to %.2f'%cc_ratio)
        except AttributeError as e:
            self.cc_ratio = cc_ratio
            self.print_info('using default cc_ratio %.2f'%cc_ratio)
        self.cc_ratio = cc_ratio

        arg_list = {'samples':self.samples,
                'horizon': self.horizon,
                'control_dim': 2,
                'temperature': self.temperature,
                'dt': self.ccmppi_dt,
                'noise_cov': self.noise_cov,
                'cc_ratio': self.cc_ratio,
                'raceline': self.discretized_raceline,
                'cuda_filename': "controller/ccmppi/ccmppi.cu",
                'max_v': self.max_speed,
                'R_diag': self.R_diag}
        if (self.model == KinematicSimulator):
            arg_list['state_dim'] = 4
            arg_list['model_name'] = KinematicSimulator
        elif (self.model == DynamicSimulator):
            arg_list['state_dim'] = 6
            arg_list['model_name'] = DynamicSimulator


        self.control_dim = arg_list['control_dim']
        self.horizon_steps = arg_list['horizon']
        self.samples_count = self.samples
        arg_list['car'] = self.car
        arg_list['track'] = self.track


        self.ccmppi = CCMPPI(arg_list)
        self.ccmppi.applyDiscreteDynamics = self.applyDiscreteDynamics
        self.additionalSetup()

        return

    def additionalSetup(self):
        self.opponent_prediction = np.repeat(self.track.obstacles[:,np.newaxis,:], self.horizon_steps + 1, axis=1)
        self.obstacles = self.track.obstacles

    def prepareDiscretizedRaceline(self):
        ss = np.linspace(0,self.track.raceline_len_m,self.discretized_raceline_len)
        rr = splev(ss%self.track.raceline_len_m,self.track.raceline_s,der=0)
        drr = splev(ss%self.track.raceline_len_m,self.track.raceline_s,der=1)
        heading_vec = np.arctan2(drr[1],drr[0])
        vv = self.track.sToV(ss) 

        # parameter, distance along track
        self.ss = ss
        self.raceline_points = np.array(rr)
        self.raceline_headings = heading_vec
        self.raceline_velocity = vv

        # describe track boundary as offset from raceline
        self.createBoundary()
        self.discretized_raceline = np.vstack([self.raceline_points,self.raceline_headings,vv, self.raceline_left_boundary, self.raceline_right_boundary]).T
        return

    def createBoundary(self,show=False):
        # construct a (self.discretized_raceline_len * 2) vector
        # to record the left and right track boundary as an offset to the discretized raceline
        left_boundary = []
        right_boundary = []

        left_boundary_points = []
        right_boundary_points = []

        for i in range(self.discretized_raceline_len):
            # find normal direction
            coord = self.raceline_points[:,i]
            heading = self.raceline_headings[i]

            left, right = self.track.preciseTrackBoundary(coord,heading)
            left_boundary.append(left)
            right_boundary.append(right)

            # debug boundary points
            left_point = (coord[0] + left * cos(heading+np.pi/2),coord[1] + left * sin(heading+np.pi/2))
            right_point = (coord[0] + right * cos(heading-np.pi/2),coord[1] + right * sin(heading-np.pi/2))

            left_boundary_points.append(left_point)
            right_boundary_points.append(right_point)


            # DEBUG
            # plot left/right boundary
            '''
            left_point = (coord[0] + left * cos(heading+np.pi/2),coord[1] + left * sin(heading+np.pi/2))
            right_point = (coord[0] + right * cos(heading-np.pi/2),coord[1] + right * sin(heading-np.pi/2))
            img = self.track.drawTrack()
            img = self.track.drawRaceline(img = img)
            img = self.track.drawPoint(img,coord,color=(0,0,0))
            img = self.track.drawPoint(img,left_point,color=(0,0,0))
            img = self.track.drawPoint(img,right_point,color=(0,0,0))
            plt.imshow(img)
            plt.show()
            '''


        self.raceline_left_boundary = left_boundary
        self.raceline_right_boundary = right_boundary

        if (show):
            img = self.track.drawTrack()
            img = self.track.drawRaceline(img = img)
            img = self.track.drawPolyline(left_boundary_points,lineColor=(0,255,0),img=img)
            img = self.track.drawPolyline(right_boundary_points,lineColor=(0,0,255),img=img)
            plt.imshow(img)
            plt.show()
            return img
        return


# given state of the vehicle and an instance of track, provide throttle and steering output
# input:
#   state: (x,y,heading,v_forward,v_sideway,omega)
#   track: track object, can be RCPtrack or skidpad
#   v_override: If specified, use this as target velocity instead of the optimal value provided by track object

# output:
#   (throttle,steering,valid,debug) 
# ranges for output:
#   throttle -1.0,self.car.max_throttle
#   steering as an angle in radians, TRIMMED to self.max_steering, left(+), right(-)
#   valid: bool, if the car can be controlled here, if this is false, then throttle will also be set to 0
#           This typically happens when vehicle is off track, and track object cannot find a reasonable local raceline
# debug: a dictionary of objects to be debugged, e.g. {offset, error in v}
    def control(self):
        car_states = self.car.states
        track = self.car.main.track
        debug_dict = {'ideal_traj':[], 'rollout_traj_vec':[]}
        # profiling
        p = self.p
        p.s()
        '''
        try:
            self.predictOpponent()
            debug_dict['opponent_prediction'] = self.opponent_prediction
        except AttributeError:
            print_error("predictOpponent() AttributeError")
            pass
        '''

        p.s("local traj")
        if self.last_s is None:
            # use self.lr as wheelbase to use center of gravity in evaluation
            retval = track.localTrajectory(car_states,wheelbase=self.car.lr,return_u=True)
            if retval is None:
                print_warning("[ctrlCcmppiWrapper:ctrlCar] localTrajectory returned None")
                ret =  (0,0,False,debug_dict)
                return ret
            else:
                # parse return value from localTrajectory
                (local_ctrl_pnt,offset,orientation,curvature,v_target,u0) = retval
                # save for estimate at next step
                self.last_s = track.uToS(u0).item()
        p.e("local traj")

        p.s("prep")
        s0 = self.last_s
        # vehicle state
        # vf: forward positive
        # vs: left positive
        # convert state used in run.py : x,y,heading,vf,vs,omega 
        #    to state in ccmppi : x,y,v,heading
        x,y,heading,vf,vs,omega = car_states

        if self.model == KinematicSimulator:
            self.states = states = np.array([x,y,vf,heading])
        elif self.model == DynamicSimulator:
            self.states = states = np.array([x,y, heading,vf,vs,omega])


        # NOTE may need revision to use previous results
        ref_control = np.zeros([self.horizon_steps,self.control_dim])
        p.e("prep")

        p.s("ccmppi")
        # dynamic simulator
        uu = self.ccmppi.control(states.copy(),self.opponent_prediction,self.control_limit)
        control = uu[0]
        throttle = control[0]
        steering = control[1]
        #print_info("[wrapper:ccmppi.control] T= %.2f, S = %.2f"%(throttle,degrees(steering)) )
        p.e("ccmppi")

        # record control energy
        self.utru = throttle*throttle*self.R_diag[0] + steering*steering*self.R_diag[1]

        # for debug
        self.debug_states = states.copy()
        self.debug_uu = uu

        self.debug_dict.update(debug_dict)

        self.car.throttle = throttle
        self.car.steering = steering
        #print("[Ccmppi] T = %.1f, S = %.1f"%(throttle, degrees(steering)))
        p.s("debug")
        try:
            if (self.plotDebugFlag):
                self.plotDebug()
            elif (self.getEstimatedTerminalCovFlag):
                self.getEstimatedTerminalCov()
            # TODO check if visualization is enabled
            self.track.plotObstacles()
            self.plotAlgorithm()
            self.plotCollision()
            pass
        except AttributeError:
            pass
        p.e("debug")
        p.e()
        return True

    def plotCollision(self):
        if (not self.main.visualization.update_visualization.is_set()):
            return
        text = f'Collision: {self.main.collision_checker.collision_count[0]}'
        img = self.main.visualization.visualization_img
        # font
        font = cv2.FONT_HERSHEY_SIMPLEX
        # org
        org = (50, 100)
        # fontScale
        fontScale = 1
        # Blue color in BGR
        color = (255, 0, 0)
        # Line thickness of 2 px
        thickness = 2
        # Using cv2.putText() method
        img = cv2.putText(img, text, org, font,
                           fontScale, color, thickness, cv2.LINE_AA)
        self.main.visualization.visualization_img = img

    def plotAlgorithm(self):
        if (not self.car.main.visualization.update_visualization.is_set()):
            return
        img = self.car.main.visualization.visualization_img
        # plot debug text
        if (self.cc_ratio < 0.01):
            text = "MPPI"
        else:
            text = "CCMPPI %.1f"%(self.cc_ratio)

        # font
        font = cv2.FONT_HERSHEY_SIMPLEX
        # org
        org = (50, 50)
        # fontScale
        fontScale = 1
        # Blue color in BGR
        color = (255, 0, 0)
        # Line thickness of 2 px
        thickness = 2
        # Using cv2.putText() method
        img = cv2.putText(img, text, org, font,
                           fontScale, color, thickness, cv2.LINE_AA)
        self.car.main.visualization.visualization_img = img



    def getEstimatedTerminalCov(self):
        # simulate where mppi think where the car will end up with
        states = self.debug_states
        # expand
        x,y,v_forward,heading = states
        v_sideway = 0
        omega = 0
        states = x,y,heading,v_forward,v_sideway,omega

        # simulate vehicle trajectory with selected rollouts
        sampled_control = self.ccmppi.debug_dict['sampled_control']
        # use only first 100
        samples = 100
        # randomly select 100
        index = random.sample(range(sampled_control.shape[0]), samples)
        sampled_control = sampled_control[index,:,:]
        rollout_traj_vec = []
        # states, sampled_control
        # DEBUG
        # plot sampled trajectories
        for k in range(samples):
            this_rollout_traj = []
            sim_states = states.copy()
            for i in range(self.horizon_steps):
                sim_states = self.applyDiscreteDynamics(sim_states,sampled_control[k,i],self.ccmppi_dt)
                x,y,heading,v_forward,v_sideway,omega = sim_states
                coord = (x,y)
                this_rollout_traj.append(coord)
            rollout_traj_vec.append(this_rollout_traj)
        self.debug_dict['rollout_traj_vec'] = rollout_traj_vec

        # calculate terminal covariance on position
        cov = np.cov(np.array(rollout_traj_vec)[:,-1,:].T)
        self.terminal_xy_cov = np.mean([cov[0,0],cov[1,1]])
        self.terminal_cov_vec.append(self.terminal_xy_cov)
        return

    def plotDebug(self):
        if (not self.car.main.visualization.update_visualization.is_set()):
            return

        # DEBUG
        # simulate where mppi think where the car will end up with
        states = self.debug_states
        # expand
        x,y,v_forward,heading = states
        v_sideway = 0
        omega = 0
        states = np.array([x,y,heading,v_forward,v_sideway,omega])
        # simulate vehicle trajectory with selected rollouts
        sampled_control = self.ccmppi.debug_dict['sampled_control']
        # use only first 100
        samples = 100
        # randomly select 100
        index = random.sample(range(sampled_control.shape[0]), samples)
        sampled_control = sampled_control[index,:,:]
        rollout_traj_vec = []
        # states, sampled_control
        # DEBUG
        # plot sampled trajectories
        for k in range(samples):
            this_rollout_traj = []
            sim_states = states.copy()
            for i in range(self.horizon_steps):
                sim_states = self.applyDiscreteDynamics(sim_states,sampled_control[k,i],self.ccmppi_dt)
                if (self.model == KinematicSimulator):
                    #x,y,vf,heading = sim_states
                    x,y, heading,vf,vs,omega = sim_states
                elif (self.model == DynamicSimulator):
                    x,y, heading,vf,vs,omega = sim_states
                coord = (x,y)
                this_rollout_traj.append(coord)
            rollout_traj_vec.append(this_rollout_traj)
        self.debug_dict['rollout_traj_vec'] = rollout_traj_vec

        # calculate terminal covariance on position
        cov = np.cov(np.array(rollout_traj_vec)[:,-1,:].T)
        self.terminal_xy_cov = np.mean([cov[0,0],cov[1,1]])
        self.terminal_cov_vec.append(self.terminal_xy_cov)

        # DEBUG
        # apply the kth sampled control
        '''
        full_state_vec = []
        sim_states = states.copy()
        k = 0
        for i in range(self.horizon_steps):
            sim_states = self.applyDiscreteDynamics(sim_states,sampled_control[k,i],self.ccmppi_dt)
            _throttle, _steering = sampled_control[k,i]
            if (self.model == KinematicSimulator):
                x,y,vf,heading = sim_states
            elif (self.model == DynamicSimulator):
                x,y, heading,vf,vs,omega = sim_states
            entry = (x,y,vf,heading,_throttle,_steering)
            full_state_vec.append(entry)
        '''


        # DEBUG
        # trajectory following synthesized control sequence
        sim_states = states.copy()
        for i in range(self.horizon_steps):
            sim_states = self.applyDiscreteDynamics(sim_states,self.debug_uu[i],self.ccmppi_dt)
            if (self.model == KinematicSimulator):
                #x,y,vf,heading = sim_states
                x,y, heading,vf,vs,omega = sim_states
            elif (self.model == DynamicSimulator):
                x,y, heading,vf,vs,omega = sim_states
            coord = (x,y)
            self.debug_dict['ideal_traj'].append(coord)

        img = self.car.main.visualization.visualization_img
        # plot sampled trajectory (if car follow one sampled control traj)
        coords_vec = self.debug_dict['rollout_traj_vec']
        for coords in coords_vec:
            img = self.car.main.track.drawPolyline(coords,lineColor=(200,200,200),img=img)

        # plot ideal trajectory (if car follow synthesized control)
        coords = self.debug_dict['ideal_traj']
        for coord in coords:
            x,y = coord
            img = self.car.main.track.drawPoint(img,(x,y),color=(255,0,0))
        img = self.car.main.track.drawPolyline(coords,lineColor=(100,0,100),img=img)

        # plot resultant trajectory from constant control
        '''
        sim_states = states.copy()
        constant_uu = np.array([0.0, 0.0])
        debug_traj = []
        for i in range(self.horizon_steps):
            sim_states = self.applyDiscreteDynamics(sim_states,constant_uu,self.ccmppi_dt)
            if (self.model == KinematicSimulator):
                x,y,vf,heading = sim_states
            elif (self.model == DynamicSimulator):
                x,y, heading,vf,vs,omega = sim_states
            coord = (x,y)
            debug_traj.append(coord)
        for coord in debug_traj:
            x,y = coord
            img = self.car.main.track.drawPoint(img,(x,y),color=(0,0,255))
        traj = np.array(debug_traj)
        '''
        #print(states.copy())
        #plt.plot(traj[:,0], traj[:,1])
        #plt.show()
        self.car.main.visualization.visualization_img = img
        return

        # plot opponent prediction
        '''
        coords_vec = self.debug_dict[car.id]['opponent_prediction']
        for coords in coords_vec:
            for coord in coords:
                x,y = coord
                img = self.car.main.track.drawPoint(img,(x,y),color=(255,0,0))
            img = self.car.main.track.drawPolyline(coords,lineColor=(100,0,0),img=img)
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
                img = self.main.track.drawPoint(img,(x,y),color=(255,0,0))
        '''



    # advance car dynamics
    # for use in visualization
    def applyDiscreteDynamics(self,states,control,dt):
        #return self.sim.updateCar(dt,control[0], control[1],external_states=state)
        # NOTE kinematic simulator and dynamic simulator use different state representation
        return self.model.advanceDynamics(states, control, car = self.car)

    def predictOpponent(self):
        self.opponent_prediction = []
        for opponent in self.opponents:
            traj = self.track.predictOpponent(opponent.state, self.horizon_steps, self.ccmppi_dt)
            self.opponent_prediction.append(traj)


if __name__=="__main__":
    pass
