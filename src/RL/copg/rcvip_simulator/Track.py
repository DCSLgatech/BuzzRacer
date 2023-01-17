import os
from xml.dom import minidom
import numpy as np
from numpy import linalg as LA
import math
import torch
import sys
sys.path.insert(0,'../..') # inorder to run within the folder
sys.path.insert(0,'..') # inorder to run within the folder
from track.TrackFactory import TrackFactory
from math import radians
import matplotlib.pyplot as plt

class Track:

    def __init__(self):
        return

    def loadOrcaTrack(self):
        self.path = "../car_racing_simulator/ORCA_OPT/"
        self.N = 999
        # ref point location
        self.X = np.loadtxt(self.path + "x_center.txt")[:, 0]
        self.Y = np.loadtxt(self.path + "x_center.txt")[:, 1]
        # ??
        self.s = np.loadtxt(self.path + "s_center.txt")
        self.phi = np.loadtxt(self.path + "phi_center.txt")
        self.kappa = np.loadtxt(self.path + "kappa_center.txt")
        self.diff_s = np.mean(np.diff(self.s))

        self.d_upper = np.loadtxt(self.path + "con_inner.txt")
        self.d_lower = np.loadtxt(self.path + "con_outer.txt")
        self.d_upper[520:565] = np.clip(self.d_upper[520:565], 0.2, 1)
        # self.d_lower[520:565] = np.clip(self.d_lower[520:565], -1, -0.2)
        self.border_angle_upper = np.loadtxt(self.path + "con_angle_inner.txt")
        self.border_angle_lower = np.loadtxt(self.path + "con_angle_outer.txt")

    def loadRcpTrack(self):
        config_xml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),'config.xml')
        '''
        try:
            config = minidom.parse('config.xml')
        except FileNotFoundError:
            config = minidom.parse('copg/rcvip_simulator/config.xml')
        '''
        config = minidom.parse(config_xml_path)

        config_track= config.getElementsByTagName('track')[0]
        self.track = TrackFactory(None,config_track,'full')
        N,X,Y,s,phi,kappa,diff_s,d_upper,d_lower,border_angle_upper,border_angle_lower = self.track.getOrcaStyleTrack()

        self.N = N
        self.X = X
        self.Y = Y
        self.s = s
        self.phi = phi
        self.kappa = kappa
        self.diff_s = diff_s

        self.d_upper = d_upper
        self.d_lower = d_lower
        # not really used
        self.border_angle_upper = border_angle_upper
        self.border_angle_lower = border_angle_lower
        return

    def posAtIndex(self, i):
        return np.array([self.X[i], self.Y[i]])

    def vecToPoint(self, index, x):
        return np.array([x[0] - self.X[index], x[1] - self.Y[index]])

    def vecTrack(self, index):
        if index >= self.N - 1:
            next_index = 0
        else:
            next_index = index + 1

        return np.array([self.X[next_index] - self.X[index], self.Y[next_index] - self.Y[index]])

    def interpol(self, name, index, rela_proj):
        index = index % self.N
        next_index = (index + 1) % self.N

        if name == "s":
            return self.s[index] + (rela_proj * (self.s[next_index] - self.s[index]))
        if name == "phi":
            return self.phi[index] + (rela_proj * (self.phi[next_index] - self.phi[index]))
        if name == "kappa":
            return self.kappa[index] + (rela_proj * (self.kappa[next_index] - self.kappa[index]))

    def fromStoPos(self, s):

        index = math.floor(s / self.diff_s)
        rela_proj = (s - self.s[index]) / self.diff_s
        pos = [self.X[index], self.Y[index]] + self.vecTrack(index) * rela_proj
        return pos

    def fromStoIndex(self, s):
        if s > self.s[-1]:
            s = s - self.s[-1]
        elif s < 0:
            s = s + self.s[-1]

        s = max(s, 0)
        s = min(s, self.s[-1] )

        index = math.floor(s / self.diff_s)
        rela_proj = (s - self.s[index]) / self.diff_s
        return [index, rela_proj]

    # x_local: s,d,mu, (progress, lateral_err, heading)
    # return: pos_global (x,y,heading)
    def fromLocaltoGlobal(self, x_local):
        s = x_local[0]
        d = x_local[1]
        mu = x_local[2]

        [index, rela_proj] = self.fromStoIndex(s)
        pos_center = [self.X[index], self.Y[index]] + self.vecTrack(index) * rela_proj
        phi = self.interpol("phi", index, rela_proj)

        pos_global = pos_center + d * np.array([-np.sin(phi), np.cos(phi)])
        heading = phi + mu
        return [pos_global[0], pos_global[1], heading]

    def wrapMu(self, mu):
        if mu < -np.pi:
            mu = mu + 2 * np.pi
        elif mu > np.pi:
            mu = mu - 2 * np.pi
        return mu

if __name__=='__main__':
    track = Track()
    track.loadRcpTrack()
    s = 0.1
    d = 0.0
    mu = radians(90)
    global_state = track.fromLocaltoGlobal((s,d,mu))
    print(f'global_state: {global_state}')
    pos_vec = []
    for s in np.linspace(0,track.track.raceline_len_m,300):
        d = 0.0
        mu = radians(90)
        global_state = track.fromLocaltoGlobal((s,d,mu))
        pos_vec.append( [global_state[0],global_state[1]] )
    pos_vec = np.array(pos_vec)
    plt.plot(pos_vec[:,0], pos_vec[:,1])
    plt.show()


