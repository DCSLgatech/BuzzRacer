# refer to paper
# The Kinematic Bicycle Model: a Consistent Model for Planning Feasible Trajectories for Autonomous Vehicles?
import numpy as np

class kinematicSimulator():

    def __init__(self,x,y,heading):
        # X,Y, velocity, heading
        self.states = np.array([x,y,0,heading])
        self.lf = 90e-3*0.95
        self.lr = 90e-3*0.05
        self.t = 0.0

        return

    def updateCar(self,dt, sim_states, throttle, steering): 
        x,y,v,heading = self.states
        beta = np.arctan( np.tan(steering) * self.lr / (self.lf+self.lr))
        dXdt = v * np.cos( heading + beta )
        dYdt = v * np.sin( heading + beta )
        dvdt = throttle
        dheadingdt = v/self.lr*np.sin(beta)

        x += dt * dXdt
        y += dt * dYdt
        v += dt * dvdt
        heading += dt * dheadingdt
        self.t += dt

        self.states = np.array([x,y,v,heading])
        sim_states = {'coord':(x,y), 'heading':heading, 'vf':v, 'omega':0}
        return sim_states


