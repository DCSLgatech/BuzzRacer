# refer to paper
# The Kinematic Bicycle Model: a Consistent Model for Planning Feasible Trajectories for Autonomous Vehicles?
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from extension import Simulator

import numpy as np
from math import radians
from common import *
from threading import Event

class KinematicSimulator(Simulator):

    def __init__(self,main):
        super().__init__(main)

        # for when a specific car instance is not speciied
        self.lr = 45e-3
        self.lf = 45e-3
        KinematicSimulator.max_v = 3.0
        KinematicSimulator.dt = self.main.dt
        self.simple_throttle_model = False

    def init(self):
        super().init()
        KinematicSimulator.simple_throttle_model = self.simple_throttle_model

        self.cars = self.main.cars
        for car in self.cars:
            self.addCar(car)
        self.main.new_state_update.set()

    # add a car to be KinematicSimulator
    # car needs to have .lf, .lr, .L .states (x,y,heading,v_forward,v_sideways,omega)
    def addCar(self,car):
        x,y,heading,v_forward,v_sideways,omega = car.states
        return

    def update(self): 
        #print_ok("[KinematicSimulator]: update")
        for car in self.cars:
            car.states = self.advanceDynamics(car.states, (car.throttle, car.steering), car)
        self.main.new_state_update.set()
        self.main.sim_t += self.main.dt
        self.matchRealTime()

    @staticmethod
    def advanceDynamics(car_states,control, car):
        lr = car.lr
        lf = car.lf
        dt = KinematicSimulator.dt
        
        '''
        throttle = np.clip(throttle, -1.0, 1.0)
        steering = np.clip(throttle, -radians(27), radians(27))
        '''
        x,y,heading,v_forward,v_sideway,omega = car_states
        v = v_forward
        # slow down if car is in collision
        '''
        if (car.in_collision):
            v *= 0.9
        '''
        throttle = control[0]
        steering = control[1]

        beta = np.arctan( np.tan(steering) * lr / (lf+lr))
        dXdt = v * np.cos( heading + beta )
        dYdt = v * np.sin( heading + beta )
        try:
            if KinematicSimulator.simple_throttle_model:
                if (v > KinematicSimulator.max_v):
                    dvdt = -0.01
                else:
                    dvdt = throttle
            else:
                dvdt = 6.17*(throttle - v/15.2 -0.333)
        except AttributeError:
            dvdt = 6.17*(throttle - v/15.2 -0.333)
        omega = dheadingdt = v/lr*np.sin(beta)

        x += dt * dXdt
        y += dt * dYdt
        v += dt * dvdt
        heading += dt * dheadingdt

        v_forward = v
        v_sideway = 0
        car_states = x,y,heading,v_forward,v_sideway,omega
        return np.array(car_states)

