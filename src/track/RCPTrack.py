#!/usr/bin/python

import numpy as np
import os.path
from numpy import isclose
import matplotlib.pyplot as plt
from math import atan2,radians,degrees,sin,cos,pi,tan,copysign,asin,acos,isnan
from scipy.interpolate import splprep, splev,CubicSpline,interp1d
from scipy.optimize import minimize_scalar,minimize,brentq
from scipy.integrate import solve_ivp
from time import sleep,time
import cv2
from PIL import Image
import pickle
from bisect import bisect

from common import *
from track.Track import Track
from util.timeUtil import execution_timer

# debugging
K_vec = [] # curvature
steering_vec = []
sim_omega_vec = []
sim_log_vec = {}

class Node:
    def __init__(self, previous=None,entrydir=None):
        # entry direction
        self.entry = entrydir
        # previous node
        self.previous = previous
        # exit direction
        self.exit = None
        self.next = None
        return
    def setExit(self,exit=None):
        self.exit = exit
        return
    def setEntry(self,entry=None):
        self.entry = entry
        return

class RCPTrack(Track):
    def __init__(self,main=None,config=None):
        Track.__init__(self,main,config)
        self.t = execution_timer(True)
        # resolution : pixels per grid side length
        self.setResolution(200)
        # for calculating derivative and integral of offset
        # for PID to use
        self.offset_history = []
        self.offset_timestamp = []
        self.log_no = 0
        self.debug = {}
        # Moved to Car.py and Visualization.py
        #self.car = cv2.imread('data/image.png',-1)

        # when localTrajectory is called multiple times, we need an initial guess for the parameter for raceline 
        self.last_u = None

    '''
    # determine if an coordinate is outside of track boundary, used in watchdog
    def isOutside(self,coord):
        grace = 1.0
        x,y = coord

        # vertical, in y direction
        rows = self.gridsize[0]
        cols = self.gridsize[1]
        res = self.resolution

        return x>cols*self.scale+grace or y>rows*self.scale+grace or x<-grace or y<-grace
    '''



    def initTrack(self,description, gridsize, scale,savepath=None):
        # build a track and save it
        # description: direction to go to reach next grid u(p), r(ight),d(own), l(eft)
        # e.g For a track like this                    
        #         /-\            
        #         | |            
        #         \_/            
        # The trajectory description, starting from the bottom left corner (origin) would be
        # uurrddll (cw)(string), it does not matter which direction is usd

        # gridsize (rows, cols), size of thr track
        # savepath, where to store the track file

        # scale : meters per grid width 0.6m
        self.scale = scale
        self.gridsize = gridsize
        self.track_length_grid = len(description)
        self.grid_sequence = []

        self.x_limit = self.gridsize[1]*self.scale
        self.y_limit = self.gridsize[0]*self.scale
        
        grid = [[None for i in range(gridsize[0])] for j in range(gridsize[1])]

        current_index = np.array([0,0])
        self.grid_sequence.append(list(current_index))
        grid[0][0] = Node()
        current_node = grid[0][0]
        lookup_table_dir = {'u':(0,1),'d':(0,-1),'r':(1,0),'l':(-1,0) }

        for i in range(len(description)):
            current_node.setExit(description[i])

            previous_node = current_node
            if description[i] in lookup_table_dir:
                current_index += lookup_table_dir[description[i]]
                self.grid_sequence.append(list(current_index))
            else:
                print("error, unexpected value in description")
                exit(1)
            if all(current_index == [0,0]):
                grid[0][0].setEntry(description[i])
                # if not met, description does not lead back to origin
                assert i==len(description)-1
                break

            # assert description does not go beyond defined grid
            assert (current_index[0]<gridsize[1]) & (current_index[1]<gridsize[0])

            current_node = Node(previous=previous_node, entrydir=description[i])
            grid[current_index[0]][current_index[1]] = current_node

        #grid[0][0].setEntry(description[-1])

        # process the linked list, replace with the following
        # straight segment = WE(EW), NS(SN)
        # curved segment = SE,SW,NE,NW, orientation of apex wrt center of grid
        lookup_table = { 'WE':['rr','ll'],'NS':['uu','dd'],'SE':['ur','ld'],'SW':['ul','rd'],'NE':['dr','lu'],'NW':['ru','dl']}
        for i in range(gridsize[1]):
            for j in range(gridsize[0]):
                node = grid[i][j]
                if node == None:
                    continue

                signature = node.entry+node.exit
                for entry in lookup_table:
                    if signature in lookup_table[entry]:
                        grid[i][j] = entry

                if grid[i][j] is Node:
                    print('bad track description: '+signature)
                    exit(1)

        self.track = grid
        return 


    def drawTrack(self, img=None,show=False):
        # show a picture of the track
        # resolution : pixels per peter
        # scale: side length of a grid (meter)
        color_side = (255,0,0)
        # boundary width / grid width
        deadzone = 0.087
        gs = int(self.resolution * self.scale)

        # prepare straight section (WE)
        straight = 255*np.ones([gs,gs,3],dtype='uint8')
        straight = cv2.rectangle(straight, (0,0),(gs-1,int(deadzone*gs)),color_side,-1)
        straight = cv2.rectangle(straight, (0,int((1-deadzone)*gs)),(gs-1,gs-1),color_side,-1)
        WE = straight

        # prepare turn section (SE)
        turn = 255*np.ones([gs,gs,3],dtype='uint8')
        turn = cv2.rectangle(turn, (0,0),(int(deadzone*gs),gs-1),color_side,-1)
        turn = cv2.rectangle(turn, (0,0),(gs-1,int(deadzone*gs)),color_side,-1)
        turn = cv2.rectangle(turn, (0,0), (int(0.5*gs),int(0.5*gs)),color_side,-1)
        turn = cv2.circle(turn, (int(0.5*gs),int(0.5*gs)),int((0.5-deadzone)*gs),(255,255,255),-1)
        turn = cv2.circle(turn, (gs-1,gs-1),int(deadzone*gs),color_side,-1)
        SE = turn

        # prepare canvas
        rows = self.gridsize[0]
        cols = self.gridsize[1]
        if img is None:
            img = 255*np.ones([gs*rows,gs*cols,3],dtype='uint8')
        lookup_table = {'SE':0,'SW':270,'NE':90,'NW':180}
        for i in range(cols):
            for j in range(rows):
                signature = self.track[i][rows-1-j]
                if signature == None:
                    continue

                if (signature == 'WE'):
                    img[j*gs:(j+1)*gs,i*gs:(i+1)*gs] = WE
                    continue
                elif (signature == 'NS'):
                    M = cv2.getRotationMatrix2D((gs/2,gs/2),90,1.01)
                    NS = cv2.warpAffine(WE,M,(gs,gs))
                    img[j*gs:(j+1)*gs,i*gs:(i+1)*gs] = NS
                    continue
                elif (signature in lookup_table):
                    M = cv2.getRotationMatrix2D((gs/2,gs/2),lookup_table[signature],1.01)
                    dst = cv2.warpAffine(SE,M,(gs,gs))
                    img[j*gs:(j+1)*gs,i*gs:(i+1)*gs] = dst
                    continue
                else:
                    print("err, unexpected track designation : " + signature)

        # some rotation are not perfect and leave a black gap
        img = cv2.medianBlur(img,5)
        '''
        if show:
            plt.imshow(img)
            plt.show()
        '''

        return img
    
    # create a heuristic raceline
    # this function stores result in self.raceline
    # seq_no: labeling the starting grid as 0, progressing through the raceline direction, the sequence number of (0,0) grid, i.e., bottom left. In other words, how many grids are between the starting grid and the origin? If starting gtid is origin grid, then seq_no is zero
    # Note self.raceline takes u, a dimensionless variable that corresponds to the control point on track
    # rance of u is (0,len(self.ctrl_pts) with 1 corresponding to the exit point out of the starting grid,
    # both 0 and len(self.ctrl_pts) pointing to the entry ctrl point for the starting grid
    # and gives a pair of coordinates in METER
    def initRaceline(self,start, start_direction,seq_no,offset=None, filename=None):
        #init a raceline from current track, save if specified 
        # start: which grid to start from, e.g. (3,3)
        # start_direction: which direction to go. 
        #note use the direction for ENTERING that grid element 
        # e.g. 'l' or 'd' for a NE oriented turn
        # NOTE you MUST start on a straight section
        self.ctrl_pts = []
        self.ctrl_pts_w = []
        self.origin_seq_no = seq_no
        if offset is None:
            offset = np.zeros(self.track_length_grid)

        # provide exit direction given signature and entry direction
        lookup_table = { 'WE':['rr','ll'],'NS':['uu','dd'],'SE':['ur','ld'],'SW':['ul','rd'],'NE':['dr','lu'],'NW':['ru','dl']}
        # provide correlation between direction (character) and directional vector
        lookup_table_dir = {'u':(0,1),'d':(0,-1),'r':(1,0),'l':(-1,0) }
        # provide right hand direction, this is for specifying offset direction 
        lookup_table_right = {'u':(1,0),'d':(-1,0),'r':(0,-1),'l':(0,1) }
        # provide apex direction
        turn_offset_toward_center = {'SE':(1,-1),'NE':(1,1),'SW':(-1,-1),'NW':(-1,1)}
        turns = ['SE','SW','NE','NW']

        center = lambda x,y : [(x+0.5)*self.scale,(y+0.5)*self.scale]

        left = lambda x,y : [(x)*self.scale,(y+0.5)*self.scale]
        right = lambda x,y : [(x+1)*self.scale,(y+0.5)*self.scale]
        up = lambda x,y : [(x+0.5)*self.scale,(y+1)*self.scale]
        down = lambda x,y : [(x+0.5)*self.scale,(y)*self.scale]

        # direction of entry
        entry = start_direction
        current_coord = np.array(start,dtype='uint8')
        signature = self.track[current_coord[0]][current_coord[1]]
        # find the previous signature, reverse entry to find ancestor
        # the precedent grid for start grid is also the final grid
        final_coord = current_coord - lookup_table_dir[start_direction]
        last_signature = self.track[final_coord[0]][final_coord[1]]

        # for referencing offset
        index = 0
        while (1):
            signature = self.track[current_coord[0]][current_coord[1]]

            # lookup exit direction
            for record in lookup_table[signature]:
                if record[0] == entry:
                    exit = record[1]
                    break

            # 0~0.5, 0 means no offset at all, 0.5 means hitting apex 
            apex_offset = 0.2

            # find the coordinate of the exit point
            # offset from grid center to centerpoint of exit boundary
            # go half a step from center toward exit direction
            exit_ctrl_pt = np.array(lookup_table_dir[exit],dtype='float')/2
            exit_ctrl_pt += current_coord
            exit_ctrl_pt += np.array([0.5,0.5])
            # apply offset, offset range (-1,1)
            exit_ctrl_pt += offset[index]*np.array(lookup_table_right[exit],dtype='float')/2
            index += 1

            exit_ctrl_pt *= self.scale
            self.ctrl_pts.append(exit_ctrl_pt.tolist())

            current_coord = current_coord + lookup_table_dir[exit]
            entry = exit

            last_signature = signature

            if (all(start==current_coord)):
                break

        # add end point to the beginning, otherwise splprep will replace pts[-1] with pts[0] for a closed loop
        # This ensures that splev(u=0) gives us the beginning point
        pts=np.array(self.ctrl_pts)
        #start_point = np.array(self.ctrl_pts[0])
        #pts = np.vstack([pts,start_point])
        end_point = np.array(self.ctrl_pts[-1])
        pts = np.vstack([end_point,pts])

        #weights = np.array(self.ctrl_pts_w + [self.ctrl_pts_w[-1]])

        # s= smoothing factor
        #a good s value should be found in the range (m-sqrt(2*m),m+sqrt(2*m)), m being number of datapoints
        m = len(self.ctrl_pts)+1
        smoothing_factor = 0.01*(m)
        tck, u = splprep(pts.T, u=np.linspace(0,self.track_length_grid,self.track_length_grid+1), s=smoothing_factor, per=1) 
        #NOTE 
        #tck, u = CubicSpline(np.linspace(0,self.track_length_grid,self.track_length_grid+1),pts) 

        # this gives smoother result, but difficult to relate u to actual grid
        #tck, u = splprep(pts.T, u=None, s=0.0, per=1) 
        self.u = u
        self.raceline = tck
        '''
        u_new = np.linspace(0,self.track_length_grid,100)
        x_new, y_new = splev(u_new, tck)
        plt.plot(x_new,y_new,'*')
        plt.show()
        '''


        # generate speed profile
        '''
        print_ok("initial trajectory")
        self.generateSpeedProfile()
        self.verifySpeedProfile()
        img_track = self.drawTrack()
        img_track = self.drawRaceline(img=img_track,points=[])
        plt.imshow(img_track)
        plt.show()
        '''
        

    def generateSpeedProfile(self, n_steps=1000):
        g = 9.81
        self.n_steps = n_steps

        # friction factor
        mu = 1.1
        # maximum longitudinial acceleration available from motor, given current longitudinal speed
        # actually around 3.3
        acc_max_motor = lambda x:3.3
        dec_max_motor = lambda x:4.5
        # generate velocity profile
        # u values for control points
        xx = np.linspace(0,self.track_length_grid,n_steps+1)
        #curvature = splev(xx,self.raceline,der=2)
        #curvature = np.linalg.norm(curvature,axis=0)

        # let raceline curve be r(u)
        # dr = r'(u), parameterized with xx/u
        dr = np.array(splev(xx,self.raceline,der=1))
        # ddr = r''(u)
        ddr = np.array(splev(xx,self.raceline,der=2))
        _norm = lambda x:np.linalg.norm(x,axis=0)
        # radius of curvature can be calculated as R = |y'|^3/sqrt(|y'|^2*|y''|^2-(y'*y'')^2)
        curvature = 1.0/(_norm(dr)**3/(_norm(dr)**2*_norm(ddr)**2 - np.sum(dr*ddr,axis=0)**2)**0.5)

        # first pass, based on lateral acceleration
        v1 = (mu*g/curvature)**0.5

        dist = lambda a,b: ((a[0]-b[0])**2+(a[1]-b[1])**2)**0.5
        # second pass, based on engine capacity and available longitudinal traction
        # start from the index with lowest speed
        min_xx = np.argmin(v1)
        v2 = np.zeros_like(v1)
        v2[min_xx] = v1[min_xx]
        for i in range(min_xx,min_xx+n_steps):
            # lateral acc at next step if the car mainains speed
            a_lat = v2[i%n_steps]**2*curvature[(i+1)%n_steps]

            # is there available traction for acceleration?
            if ((mu*g)**2-a_lat**2)>0:
                a_lon_available_traction = ((mu*g)**2-a_lat**2)**0.5
                # constrain with motor capacity
                a_lon = min(acc_max_motor(v2[i%n_steps]),a_lon_available_traction)

                (x_i, y_i) = splev(xx[i%n_steps], self.raceline, der=0)
                (x_i_1, y_i_1) = splev(xx[(i+1)%n_steps], self.raceline, der=0)
                # distance between two steps
                ds = dist((x_i, y_i),(x_i_1, y_i_1))
                # assume vehicle accelerate uniformly between the two steps
                v2[(i+1)%n_steps] =  min((v2[i%n_steps]**2 + 2*a_lon*ds)**0.5,v1[(i+1)%n_steps])
            else:
                v2[(i+1)%n_steps] =  v1[(i+1)%n_steps]

        v2[-1]=v2[0]
        # third pass, backwards for braking
        min_xx = np.argmin(v2)
        v3 = np.zeros_like(v1)
        v3[min_xx] = v2[min_xx]
        for i in np.linspace(min_xx,min_xx-n_steps,n_steps+2):
            i = int(i)
            a_lat = v3[i%n_steps]**2*curvature[(i-1+n_steps)%n_steps]
            a_lon_available_traction = abs((mu*g)**2-a_lat**2)**0.5
            a_lon = min(dec_max_motor(v3[i%n_steps]),a_lon_available_traction)
            #print(a_lon)

            (x_i, y_i) = splev(xx[i%n_steps], self.raceline, der=0)
            (x_i_1, y_i_1) = splev(xx[(i-1+n_steps)%n_steps], self.raceline, der=0)
            # distance between two steps
            ds = dist((x_i, y_i),(x_i_1, y_i_1))
            #print(ds)
            v3[(i-1+n_steps)%n_steps] =  min((v3[i%n_steps]**2 + 2*a_lon*ds)**0.5,v2[(i-1+n_steps)%n_steps])
            #print(v3[(i-1+n_steps)%n_steps],v2[(i-1+n_steps)%n_steps])
            pass

        v3[-1]=v3[0]

        # call with self.targetVfromU(u) alwayos u is in range [0,len(self.ctrl_pts)]
        self.targetVfromU = interp1d(xx,v3,kind='cubic')
        self.v1 = interp1d(xx,v1,kind='cubic')
        self.v2 = interp1d(xx,v2,kind='cubic')
        self.v3 = interp1d(xx,v3,kind='cubic')

        self.max_v = max(v3)
        self.min_v = min(v3)

        # debug target v curve fitting
        #p0, = plt.plot(xx,v3,'*',label='original')
        #xxx = np.linspace(0,self.track_length_grid,10*n_steps)
        #sampleV = self.targetVfromU(xxx)
        #p1, = plt.plot(xxx,sampleV,label='fitted')
        #plt.legend(handles=[p0,p1])
        #plt.show()


        # three pass of velocity profile
        p0, = plt.plot(curvature, label='curvature')
        p1, = plt.plot(v1,label='1st pass')
        p2, = plt.plot(v2,label='2nd pass')
        p3, = plt.plot(v3,label='3rd pass')
        plt.legend(handles=[p1,p2,p3])
        plt.show()


    # ---------- for curvature norm minimization -----
    def prepareTrack(self,):
        # prepare full track
        track_size = (6,4)
        self.initTrack('uuurrullurrrdddddluulddl',track_size, scale=0.6)
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
        #self.initRaceline((3,3),'d',10,offset=adjustment)
        self.initRaceline((3,3),'d',10)
        return

    # save raceline to pickle file
    def save(self,filename=None):
        if filename is None:
            filename = "raceline.p"

        # assemble save data
        save = {}
        save['grid_sequence'] = self.grid_sequence
        save['scale'] = self.scale
        save['origin_seq_no'] = self.origin_seq_no
        save['track_length'] = self.track_length_grid
        save['raceline'] = self.raceline
        save['gridsize'] = self.gridsize
        save['resolution'] = self.resolution
        save['targetVfromU'] = self.targetVfromU
        save['track'] = self.track
        save['min_v'] = self.min_v
        save['max_v'] = self.max_v

        with open('./data/'+filename, 'wb') as f:
            pickle.dump(save,f)
        print_ok("track and raceline saved")

    # load quadratically smoothed raceline
    def load(self,filename=None):
        # get data folder abs path
        thisdir = os.path.dirname(os.path.abspath(__file__))
        basedir = os.path.dirname(thisdir)
        if filename is None:
            filename = "raceline.p"
        try:
            with open(basedir+'/data/'+filename, 'rb') as f:
                save = pickle.load(f)
        except FileNotFoundError:
            print_error("can't find "+filename+", run qpSmooth.py first")

        # restore save data
        self.grid_sequence = save['grid_sequence']
        self.scale = save['scale']
        self.origin_seq_no = save['origin_seq_no']
        self.track_length_grid = save['track_length']
        self.raceline = save['raceline']
        self.gridsize = save['gridsize']
        #self.resolution = save['resolution']
        self.targetVfromU = save['targetVfromU']
        self.track = save['track']
        self.min_v = save['min_v']
        self.max_v = save['max_v']
        self.x_limit = self.gridsize[1]*self.scale
        self.y_limit = self.gridsize[0]*self.scale

        print_ok("track and raceline loaded")
        self.reconstructRaceline()
        return

    # calculate distance
    def calcPathDistance(self,u0,u1):
        s = 0
        steps = 10
        uu = np.linspace(u0,u1,steps)
        xx,yy = splev(uu,self.raceline,der=0)
        dx = np.diff(xx)
        dy = np.diff(yy)
        s = np.sum(np.sqrt(dx**2+dy**2))
        return s

    # new representation of raceline via piecewise curvature map along path
    def discretizePath(self,steps=1000):
        u = np.linspace(0,self.u[-1],steps)
        # s[k]: path distance from k to k+1
        s = np.zeros_like(u)
        for i in range(1,steps):
            s[i] = self.calcPathDistance(u[i-1],u[i])
        S = np.cumsum(s)
        print("discretized path total length is: %.2f"%S[-1])

        # K: curvature
        # let raceline curve be r(u)
        # dr = r'(u), parameterized with xx/u
        dr = np.array(splev(u,self.raceline,der=1))
        # ddr = r''(u)
        ddr = np.array(splev(u,self.raceline,der=2))
        _norm = lambda x:np.linalg.norm(x,axis=0)
        # radius of curvature can be calculated as R = |y'|^3/sqrt(|y'|^2*|y''|^2-(y'*y'')^2)
        curvature = 1.0/(_norm(dr)**3/(_norm(dr)**2*_norm(ddr)**2 - np.sum(dr*ddr,axis=0)**2)**0.5)

        # we need signed curvature, get that with cross product dr and ddr
        cross = np.cross(dr.T,ddr.T)
        curvature = np.copysign(curvature,cross)

        # resample K at uniform interval of s
        S_interp = interp1d(S,curvature, kind='cubic')
        self.S = np.linspace(0,S[-1],steps)
        self.ds = S[-1]/(steps-1)
        self.K = S_interp(self.S)

        # phi0: heading at u=0
        x,y = splev(0,self.raceline,der=1)

        self.phi0 = atan2(y,x)
        self.x0,self.y0 = splev(0,self.raceline,der=0)

        # DEBUG
        '''
        plt.plot(S,curvature)
        plt.plot(self.S,self.K)
        plt.show()
        '''

    def getOrcaStyleTrack(self):
        # ORCA compatible representation
        N = self.discretized_raceline_len = 1024
        s = self.s_vec = s_vec = np.linspace(0,self.raceline_len_m,self.discretized_raceline_len)
        # resample to fixed interval s_vec
        self.r = ref_path = np.array(splev(s_vec%self.raceline_len_m,self.raceline_s,der=0)).T
        X = self.r[:,0].flatten()
        Y = self.r[:,1].flatten()


        diff_s = s_vec[1]-s_vec[0]
        dr, ddr = self.calcDerivative(ref_path,ds=diff_s)
        self.dr = dr
        self.ddr = ddr
        # TODO verify sign
        kappa = self.calcCurvature(dr,ddr)

        # raceline heading
        #dr = splev(s_vec%self.raceline_len_m,self.raceline_s,der=1)
        phi = np.arctan2(dr[:,1],dr[:,0])
        old_phi = phi.copy()
        # wrap angle
        d_phi = np.diff(phi)
        d_phi = (d_phi + np.pi) % (2*np.pi) - np.pi
        phi = phi[0] + np.hstack([0,np.cumsum(d_phi)]) + 2*np.pi

        # describe track boundary as offset from raceline
        left_limit, right_limit = self.createBoundary(ref_path,phi)
        # TODO: verify sign and upper/lower ordering
        d_upper = np.array(left_limit)
        d_lower = -np.array(right_limit)

        border_angle_upper = phi + 40/180*np.pi
        border_angle_lower = phi - 40/180*np.pi

        # ccw 90 deg
        #R = np.array([[0,-1],[1,0]])
        #tangent_dir = (R @ self.dr.T)/np.linalg.norm(self.dr,axis=1)
        #self.left_boundary = (tangent_dir * self.left_limit).T + self.ref_path
        #self.right_boundary = (tangent_dir * self.right_limit).T + self.ref_path
        return (N,X,Y,s,phi,kappa,diff_s,d_upper,d_lower,border_angle_upper,border_angle_lower)


    def calcDerivative(self,curve,ds):
        # find first and second derivative
        dr = []
        ddr = []
        n = curve.shape[0]
        for i in range(1,n-1):
            rl = curve[i-1,:]
            r = curve[i,:]
            rr = curve[i+1,:]
            points = [rl, r, rr]
            ((al,a,ar),(bl,b,br)) = self.lagrangeDer(points,ds=[ds,ds])
            dr.append(al*rl+a*r+ar*rr)
            ddr.append(bl*rl+b*r+br*rr)
        dr = np.array(dr)
        ddr = np.array(ddr)
        dr = np.vstack([dr[0],dr,dr[-1]])
        ddr = np.vstack([ddr[0],ddr,ddr[-1]])
        return (dr,ddr)

    # right turn negative curvature
    def calcCurvature(self,dr_vec,ddr_vec):
        # ccw 90 deg
        A = np.array([[0,-1],[1,0]])
        a = (A @ dr_vec.T).T
        b = ddr_vec
        curvature = np.sum(a*b,axis=1).flatten()
        return curvature

    # given three points, calculate first and second derivative as a linear combination of the three points rl, r, rr, which stand for r_(k-1), r_k, r_(k+1)
    # return: 2*3, tuple
    #       ((al, a, ar),
    #        (bl, b, br))
    # where f'@r = al*rl + a*r + ar*rr
    # where f''@r = bl*rl + b*r + br*rr
    # ds, arc length between rl,r and r, rr 
    # if not specified, |r-rl|_2 will be used as approximation
    def lagrangeDer(self,points,ds=None):
        rl,r,rr = points
        dist = lambda x,y:((x[0]-y[0])**2 + (x[1]-y[1])**2)**0.5
        if ds is None:
            sl = -dist(rl,r)
            sr = dist(r,rr)
        else:
            sl = -ds[0]
            sr = ds[1]

        try:
            al = - sr/sl/(sl-sr)
            a = -(sl+sr)/sl/sr
            ar = -sl/sr/(sr-sl)

            bl = 2/sl/(sl-sr)
            b = 2/sl/sr
            br = 2/sr/(sr-sl)
        except Warning as e:
            print(e)

        return ((al,a,ar),(bl,b,br))

    # constrain >= 0
    # given coord=(x,y) unit:m
    # calculate distance to left/right boundary
    # return min(wl, wr), distance to closest side
    def checkTrackBoundary(self,coord):
        # figure out which grid the coord is in
        # grid coordinate, (col, row), col starts from left and row starts from bottom, both indexed from 0
        nondim= np.array(np.array(coord)/self.scale//1,dtype=int)
        nondim[0] = np.clip(nondim[0],0,len(self.track)-1).astype(int)
        nondim[1] = np.clip(nondim[1],0,len(self.track[0])-1).astype(int)

        # e.g. 'WE','SE'
        grid_type = self.track[nondim[0]][nondim[1]]

        # change ref frame to tile local ref frame
        x_local = coord[0]/self.scale - nondim[0]
        y_local = coord[1]/self.scale - nondim[1]

        # find the distance to track sides
        # boundary/wall width / grid side length
        deadzone = 0.087
        straights = ['WE','NS']
        turns = ['SE','SW','NE','NW']
        if grid_type in straights:
            if grid_type == 'WE':
                # track section is staight, arranged horizontally
                # remaining space on top (negative means coord outside track
                wl = y_local - deadzone
                wr = 1 - deadzone - y_local
            if grid_type == 'NS':
                # track section is staight, arranged vertically
                # remaining space on left (negative means coord outside track
                wl = x_local - deadzone
                wr = 1 - deadzone - x_local
        elif grid_type in turns:
            if grid_type == 'SE':
                apex = (1,0)
            if grid_type == 'SW':
                apex = (0,0)
            if grid_type == 'NE':
                apex = (1,1)
            if grid_type == 'NW':
                apex = (0,1)
            radius = ((x_local - apex[0])**2 + (y_local - apex[1])**2)**0.5
            wl = 1-deadzone-radius
            wr = radius - deadzone
        return min(wl,wr)

    # given coordinate and heading, calculate precise boundary to left and right
    # return a vector (dist_to_left, dist_to_right)
    def preciseTrackBoundary(self,coord,heading):
        heading = (heading + np.pi)%(2*np.pi) - np.pi
        # figure out which grid the coord is in
        # grid coordinate, (col, row), col starts from left and row starts from bottom, both indexed from 0
        nondim= np.array(np.array(coord)/self.scale//1,dtype=int)
        nondim[0] = np.clip(nondim[0],0,len(self.track)-1).astype(int)
        nondim[1] = np.clip(nondim[1],0,len(self.track[0])-1).astype(int)

        # e.g. 'WE','SE'
        grid_type = self.track[nondim[0]][nondim[1]]

        # change ref frame to tile local ref frame
        x_local = coord[0]/self.scale - nondim[0]
        y_local = coord[1]/self.scale - nondim[1]

        # find the distance to track sides
        # boundary/wall width / grid side length
        deadzone = 0.087
        straights = ['WE','NS']
        turns = ['SE','SW','NE','NW']
        if grid_type in straights:
            if grid_type == 'WE':
                # track section is staight, arranged horizontally
                # remaining space on top (negative means coord outside track
                grid_down = y_local - deadzone
                grid_up = 1 - deadzone - y_local
                if (heading > -np.pi/2 and heading < np.pi/2):
                    left = grid_up / cos(heading)
                    right = grid_down / cos(heading)
                else:
                    left = - grid_down / cos(heading)
                    right = - grid_up / cos(heading)

            if grid_type == 'NS':
                # track section is staight, arranged vertically
                # remaining space on left (negative means coord outside track
                grid_left= x_local - deadzone
                grid_right = 1 - deadzone - x_local
                if (heading > 0 and heading < np.pi):
                    left = grid_left/ sin(heading)
                    right = grid_right/ sin(heading)
                else:
                    left = - grid_right/ sin(heading)
                    right = - grid_left/ sin(heading)
                    # TODO
        elif grid_type in turns:
            step_size = 0.01

            # find left boundary
            left = 0.0
            flag_in_limit = True
            while (flag_in_limit):
                left_point = (coord[0] + left * cos(heading+np.pi/2),coord[1] + left * sin(heading+np.pi/2))
                flag_in_limit = self.checkTrackBoundary(left_point) > 0
                left += step_size

            # find right boundary
            right = 0.0
            flag_in_limit = True
            while (flag_in_limit):
                right_point = (coord[0] + right * cos(heading-np.pi/2),coord[1] + right * sin(heading-np.pi/2))
                flag_in_limit = self.checkTrackBoundary(right_point) > 0
                right += step_size

            # convert metric unit to dimensionless unit
            left /= self.scale
            right /= self.scale

            '''
            if grid_type == 'SE':
                apex = (1,0)
            if grid_type == 'SW':
                apex = (0,0)
            if grid_type == 'NE':
                apex = (1,1)
            if grid_type == 'NW':
                apex = (0,1)
            radius = ((x_local - apex[0])**2 + (y_local - apex[1])**2)**0.5
            grid_out = 1-deadzone-radius
            grid_in = radius - deadzone



            if grid_type == 'SE':
                if (heading > -0.25*np.pi and heading < 0.75*np.pi):
                    left = 0.1
                    right = 0.1
                else:
                    left = 0.1
                    right = 0.1
            if grid_type == 'SW':
                if (heading > -0.75*np.pi and heading < 0.25*np.pi):
                    left = 0.1
                    right = 0.1
                else:
                    left = 0.1
                    right = 0.1
            if grid_type == 'NE':
                if (heading > 0.25*np.pi and heading < 1.25*np.pi):
                    left = 0.1
                    right = 0.1
                else:
                    left = 0.1
                    right = 0.1
            if grid_type == 'NW':
                if (heading > 0.35*np.pi and heading < -0.25*np.pi):
                    left = 0.1
                    right = 0.1
                else:
                    left = 0.1
                    right = 0.1
            '''


        return (left*self.scale,right*self.scale)

    # distance between start and end of path, 
    # must be sufficiently close
    def pathGap(self,):
        return

    # convert from K(s) space to cartesian X,Y(s) space using Fresnel integral
    def kenselTransform(self,K,ds):
        steps = K.shape[0]
        s_total = ds*(steps-1)
        S = np.linspace(0,s_total,steps)
        # state variable X,Y,Heading
        Kfun = interp1d(S,K)
        def kensel(s,x):
            return [ cos(x[2]), sin(x[2]), Kfun(s)]

        s_span = [0,s_total]
        x0 = (self.x0,self.y0,self.phi0)
        sol = solve_ivp(kensel,s_span, x0, method='LSODA',t_eval = S )
        x = sol.y[0]
        y = sol.y[1]
        return x,y

    # generate an array of boundary clearance
    def boundaryClearanceVector(self,k):
        x,y = self.kenselTransform(k,self.ds)
        retval = [self.checkTrackBoundary((xx,yy)) for xx,yy in zip(x,y)]
        # DEBUG
        '''
        for i in retval:
            if i<0:
                print("unmet constrain!")
                break
        '''
        return retval
        

    # ---------- for curvature norm minimization -----

    # draw point corresponding to u
    def drawPointU(self,img,uu):
        rows = self.gridsize[0]
        x_new, y_new = splev(uu, self.raceline, der=0)

        for x,y in zip(x_new,y_new):
            img = self.drawPoint(img,(x,y))
        return img
    
    # draw the raceline from self.raceline
    def drawRaceline(self,lineColor=(0,0,255), img=None,points=None):

        rows = self.gridsize[0]
        cols = self.gridsize[1]
        res = int(self.resolution*self.scale)

        # this gives smoother result, but difficult to relate u to actual grid
        #u_new = np.linspace(self.u.min(),self.u.max(),1000)

        # the range of u is len(self.ctrl_pts) + 1, since we copied one to the end
        # x_new and y_new are in non-dimensional grid unit
        u_new = np.linspace(0,self.track_length_grid,1000)
        x_new, y_new = splev(u_new, self.raceline, der=0)
        # convert to visualization coordinate
        x_new *= self.resolution 
        y_new *= self.resolution
        y_new = self.resolution*self.scale*rows - y_new

        if img is None:
            img = np.zeros([res*rows,res*cols,3],dtype='uint8')

        pts = np.vstack([x_new,y_new]).T
        # for polylines, pts = pts.reshape((-1,1,2))
        pts = pts.reshape((-1,2))
        pts = pts.astype(int)
        # render different color based on speed
        # slow - red, fast - green (BGR)
        v2c = lambda x: int((x-self.min_v)/(self.max_v-self.min_v)*255)
        getColor = lambda v:(0,v2c(v),255-v2c(v))
        for i in range(len(u_new)-1):
            img = cv2.line(img, tuple(pts[i]),tuple(pts[i+1]), color=getColor(self.targetVfromU(u_new[i]%self.track_length_grid)), thickness=3) 

        # plot reference points
        #img = cv2.polylines(img, [pts], isClosed=True, color=lineColor, thickness=3) 
        if not (points is None):
            for point in points:
                x = point[0]
                y = point[1]
                x *= self.resolution
                y *= self.resolution
                y = self.resolution*self.scale*rows - y
                
                img = cv2.circle(img, (int(x),int(y)), 5, (0,0,255),-1)

        return img

    # given state of robot
    # find the closest point on raceline to center of FRONT axle
    # calculate the lateral offset (in meters), this will be reported as offset, which can be added directly to raceline orientation (after multiplied with an aggressiveness coefficient) to obtain desired front wheel orientation
    # calculate the local derivative
    # coord should be referenced from the origin (bottom left(edited)) of the track, in meters
    # negative offset means coord is to the right of the raceline, viewing from raceline init direction
    # wheelbase is needed to calculate the local trajectory closes to the front axle instead of the old axle
    def localTrajectory(self,state,wheelbase=90e-3,return_u=False):
        # figure out which grid the coord is in
        coord = np.array([state[0],state[1]])
        heading = state[2]
        # find the coordinate of center of front axle
        coord[0] += wheelbase*cos(heading)
        coord[1] += wheelbase*sin(heading)
        heading = state[2]
        # grid coordinate, (col, row), col starts from left and row starts from bottom, both indexed from 0
        # coord should be given in meters
        nondim= np.array((coord/self.scale)//1,dtype=int)

        # distance squared, not need to find distance here
        dist_2 = lambda a,b: (a[0]-b[0])**2+(a[1]-b[1])**2
        fun = lambda u: dist_2(splev(u%self.track_length_grid,self.raceline),coord)
        # last_u is the seq found last time, which should be a good estimate of where to start
        # disable this functionality since it doesn't handle multiple cars
        self.last_u = None
        if self.last_u is None:
            # the seq here starts from origin
            seq = -1
            # figure out which u this grid corresponds to 
            for i in range(len(self.grid_sequence)):
                if nondim[0]==self.grid_sequence[i][0] and nondim[1]==self.grid_sequence[i][1]:
                    seq = i
                    break

            if seq == -1:
                print("error, coord not on track, x = %.2f, y=%.2f"%(coord[0],coord[1]))
                return None

            # the grid that contains the coord
            #print("in grid : " + str(self.grid_sequence[seq]))

            # find the closest point to the coord
            # because we wrapped the end point to the beginning of sample point, we need to add this offset
            # Now seq would correspond to u in raceline, i.e. allow us to locate the raceline at that section
            seq += self.origin_seq_no
            seq %= self.track_length_grid

            # this gives a close, usually preceding raceline point, this does not give the closest ctrl point
            # due to smoothing factor
            #print("neighbourhood raceline pt " + str(splev(seq,self.raceline)))

            # determine which end is the coord closer to, since seq points to the previous control point,
            # not necessarily the closest one
            if fun(seq+1) < fun(seq):
                seq += 1
            if fun(seq-1) < fun(seq):
                seq -= 1
        else:
            seq = self.last_u

        # Goal: find the point on raceline closest to coord
        # i.e. find x that minimizes fun(x)
        # we know x will be close to seq

        # easy method
        #brute force, This takes 77% of runtime. 
        #lt.s('minimize_scalar')
        #res = minimize_scalar(fun,bounds=[seq-0.6,seq+0.6],method='Bounded')
        #lt.e('minimize_scalar')

        # improved method: from observation, fun(x) is quadratic in proximity of seq
        # we assume it to be ax^3 + bx^2 + cx + d and formulate this minimization as a linalg problem
        # sample some points to build the trinomial simulation
        self.debug['seq'] = seq
        iv = np.array([-0.6,-0.3,0,0.3,0.6])+seq
        # formulate linear problem
        A = np.vstack([iv**3, iv**2,iv,[1,1,1,1,1]]).T
        #B = np.mat([fun(x0), fun(x1), fun(x2)]).T
        B = fun(iv).T
        #abc = np.linalg.solve(A,B)
        abc = np.linalg.lstsq(A,B, rcond=-1)[0]
        a = abc[0]
        b = abc[1]
        c = abc[2]
        d = abc[3]
        fun = lambda x : a*x*x*x + b*x*x + c*x + d
        fit = minimize(fun, x0=seq, method='L-BFGS-B', bounds=((seq-0.6,seq+0.6),))
        min_fun_x = fit.x[0]
        self.last_u = min_fun_x%self.track_length_grid

        min_fun_val = float(fit.fun)
        # find min val
        #x = min_fun_x = (-b+(b*b-3*a*c)**0.5)/(3*a)
        #if (seq-0.6<x<seq+0.6):
        #    min_fun_val = a*x*x*x + b*x*x + c*x + d
        #else:
        #    # XXX this is a bit sketchy, maybe none of them is right
        #    x = (-b+(b*b-3*a*c)**0.5)/(3*a)
        #    min_fun_val = a*x*x*x + b*x*x + c*x + d

        '''
        xx = np.linspace(seq-0.6,seq+0.6)
        plt.plot(xx,fun(xx),'b--')
        plt.plot(iv,fun(iv),'bo')
        plt.plot(xx,a*xx**3+b*xx**2+c*xx+d,'r-')
        plt.plot(iv,a*iv**3+b*iv**2+c*iv+d,'ro')
        plt.show()
        '''

        #lt.track('x err', abs(min_fun_x-res.x))
        #lt.track('fun err',abs(min_fun_val-res.fun))
        #print('x err', abs(min_fun_x-res.x))
        #print('fun err',abs(min_fun_val-res.fun))

        raceline_point = splev(min_fun_x%self.track_length_grid,self.raceline)
        #raceline_point = splev(res.x,self.raceline)

        der = splev(min_fun_x%self.track_length_grid,self.raceline,der=1)
        #der = splev(res.x,self.raceline,der=1)

        if (False):
            print("Seek local trajectory")
            print("u = "+str(min_fun_x))
            print("dist = "+str(min_fun_val**0.5))
            print("closest point on track: "+str(raceline_point))
            print("closest point orientation: "+str(degrees(atan2(der[1],der[0]))))

        # calculate whether offset is ccw or cw
        # achieved by finding cross product of vec(raceline_orientation) and vec(ctrl_pnt->test_pnt)
        # then find sin(theta)
        # negative offset means car is to the right of the trajectory
        vec_raceline = (der[0],der[1])
        vec_offset = coord - raceline_point
        cross_theta = np.cross(vec_raceline,vec_offset)


        vec_curvature = splev(min_fun_x%self.track_length_grid,self.raceline,der=2)
        norm_curvature = np.linalg.norm(vec_curvature)
        # gives right sign for omega, this is indep of track direction since it's calculated based off vehicle orientation
        #cross_curvature = np.cross((cos(heading),sin(heading)),vec_curvature)
        cross_curvature = der[0]*vec_curvature[1]-der[1]*vec_curvature[0]

        # return target velocity
        request_velocity = self.targetVfromU(min_fun_x%self.track_length_grid)

        # reference point on raceline,lateral offset, tangent line orientation, curvature(signed), v_target(not implemented)
        if return_u:
            return (raceline_point,copysign(abs(min_fun_val)**0.5,cross_theta),atan2(der[1],der[0]),copysign(norm_curvature,cross_curvature),request_velocity,min_fun_x%self.track_length_grid)
        else:
            return (raceline_point,copysign(abs(min_fun_val)**0.5,cross_theta),atan2(der[1],der[0]),copysign(norm_curvature,cross_curvature),request_velocity)


    # create two function to map between u(raceline parameter)<->s(distance along racelien)
    # also create mapping between s -> v_ref
    # also create raceline_s, raceline parameterized with s
    def reconstructRaceline(self):
        s_vec = [0]
        n_steps = 1000
        uu = np.linspace(0,self.track_length_grid,n_steps+1)
        dist = lambda a,b: ((a[0]-b[0])**2+(a[1]-b[1])**2)**0.5
        path_len = 0
        for i in range(n_steps):
            (x_i, y_i) = splev(uu[i%n_steps], self.raceline, der=0)
            (x_i_1, y_i_1) = splev(uu[(i+1)%n_steps], self.raceline, der=0)
            # distance between two steps
            ds = dist((x_i, y_i),(x_i_1, y_i_1))
            path_len += ds
            s_vec.append(path_len)

        ss = np.array(s_vec)
        vv = self.targetVfromU(uu%self.track_length_grid)

        # using interp1d functions can cause some overhead
        # when absolute speed is needed, use lookup tables
        # this may lose some accuracy but with larger n_step
        # and moderate change in velocity this should not be an issue
        self.sToV_lut = lambda x: self.v_lut[bisect(self.s_lut,x)]
        self.s_lut = ss
        self.v_lut = vv

        self.uToS = interp1d(uu,ss,kind='cubic')
        self.sToU = interp1d(ss,uu,kind='cubic')
        self.sToV = interp1d(ss,vv,kind='cubic')
        self.raceline_len_m = path_len
        #print("verify u and s mapping accuracy")
        #ss_remap = self.uToS(self.sToU(ss))
        #print("mean error in s %.5f m "%(np.mean(np.abs(ss-ss_remap))))
        #print("max error in s %.5f m "%(np.max(np.abs(ss-ss_remap))))

        # convert self.raceline(parameterized w.r.t. u) 
        # to self.raceline_s (parameterized w.r.t. s, distance along path)
        rr = splev(uu%self.track_length_grid,self.raceline)
        tck, u = splprep(rr, u=ss,s=0,per=1) 
        self.raceline_s = tck
        return

    # get future reference point for dynamic MPC
    # Inputs:
    # state: vehicle state, same as in self.localTrajectory()
    # p : lookahead steps
    # dt : time between each lookahead steps

    # Return:
    # xref : np array of size (p+1)*2, there are p+1 entries because xref0 is the ref point for current location, and then there are p projection points
    # psi_ref : reference heading at the reference points, size (p+1)*2
    # v_ref : reference heading at the reference points, size (p+1)*2
    # valid : a boolean indicating whether the function was able to find a valid result
    # The function first finds a point on trajectory closest to vehicle location with localTrajectory(), then find p points down the trajectory that are spaced vk * dt apart in path length. vk is the reference velocity at those points

    def getRefPoint(self, state, p, dt, reverse=False):
        t = self.t

        t.s()
        if reverse:
            print_error("reverse is not implemented")
        # set wheelbase to 0 to get point closest to vehicle CG
        t.s("local traj")
        retval = self.localTrajectory(state,wheelbase=0.102/2.0,return_u=True)
        t.e("local traj")
        if retval is None:
            return None,None,False

        # parse return value from localTrajectory
        (local_ctrl_pnt,offset,orientation,curvature,v_target,u0) = retval
        if isnan(orientation):
            return None,None,False

        # calculate s value for projection ref points
        t.s("find s")
        s0 = self.uToS(u0).item()
        v0 = self.targetVfromU(u0%self.track_length_grid).item()
        der = splev(u0%self.track_length_grid,self.raceline,der=1)
        heading0 = atan2(der[1],der[0])
        t.e("find s")

        t.s("curvature")
        _norm = lambda x:np.linalg.norm(x,axis=0)
        # gives right sign for omega, this is indep of track direction since it's calculated based off vehicle orientation

        dr = np.array(splev(u0%self.track_length_grid,self.raceline,der=1))
        ddr = vec_curvature = np.array(splev(u0%self.track_length_grid,self.raceline,der=2))
        cross_curvature = der[0]*vec_curvature[1]-der[1]*vec_curvature[0]
        curvature = 1.0/(_norm(dr)**3/(_norm(dr)**2*_norm(ddr)**2 - np.sum(dr*ddr,axis=0)**2)**0.5)

        t.e("curvature")

        # curvature needs to be signed to indicate whether signage target angular velocity
        # a cross product gives right signage for omega, this is indep of track direction since it's calculated based off vehicle orientation
        cross_curvature = der[0]*vec_curvature[1]-der[1]*vec_curvature[0]

        #k_vec.append(norm_curvature)
        #k_sign_vec.append(cross_curvature)
        k_vec = curvature
        k_sign_vec = cross_curvature


        s_vec = [s0]
        v_vec = [v0]
        heading_vec = [heading0]
        k_vec = [curvature]
        k_sign_vec = [cross_curvature]

        u_vec = [u0]

        t.s("main loop")
        for k in range(1,p+1):
            s_k = s_vec[-1] + v_vec[-1] * dt
            s_vec.append(s_k)
            # find ref velocity for projection ref points
            # TODO adjust ref velocity for current vehicle velocity
            #v_k = self.targetVfromU(u_k%self.track_length_grid)
            #v_k = self.sToV(s_k%self.raceline_len_m)
            v_k = self.sToV_lut(s_k%self.raceline_len_m)
            v_vec.append(v_k)
        t.e("main loop")

        #u_vec = np.array(u_vec)%self.track_length_grid
        # find ref heading for projection ref points
        t.s("psi")
        #der = np.array(splev(u_vec,self.raceline,der=1))
        s_vec = np.array(s_vec)%self.raceline_len_m
        der = np.array(splev(s_vec,self.raceline_s,der=1))
        #heading_k = atan2(der[1],der[0])
        #heading_vec.append(heading_k)
        t.e("psi")
        # find ref coordinates for projection ref points

        t.s("coord")
        coord_vec = np.array(splev(s_vec,self.raceline_s)).T
        t.e("coord")

        t.s("K")

        #norm_curvature = np.linalg.norm(vec_curvature,axis=1)
        dr = np.array(splev(s_vec,self.raceline_s,der=1))
        ddr = vec_curvature = np.array(splev(s_vec,self.raceline_s,der=2))

        curvature = 1.0/(_norm(dr)**3/(_norm(dr)**2*_norm(ddr)**2 - np.sum(dr*ddr,axis=0)**2)**0.5)

        # curvature needs to be signed to indicate whether signage target angular velocity
        # a cross product gives right signage for omega, this is indep of track direction since it's calculated based off vehicle orientation
        cross_curvature = der[0,:]*vec_curvature[1,:]-der[1,:]*vec_curvature[0,:]

        #k_vec.append(norm_curvature)
        #k_sign_vec.append(cross_curvature)
        k_vec = curvature
        k_sign_vec = cross_curvature




        # TODO check dimension
        k_signed_vec = np.copysign(k_vec,k_sign_vec)

        x,y,heading,vf,vs,omega = state
        e_heading = ((heading - heading0) + pi/2.0 ) % (2*pi) - pi/2.0
        t.e("K")

        t.e()
        #return offset, e_heading, np.array(v_vec),np.array(k_signed_vec), np.array(coord_vec),True
        return offset, e_heading, np.array(v_vec),np.array(k_signed_vec), np.array(coord_vec),True

    def getRefXYVheading(self, state, p, dt, reverse=False):
        t = self.t

        t.s()
        if reverse:
            print_error("reverse is not implemented")
        # set wheelbase to 0 to get point closest to vehicle CG
        t.s("local traj")
        retval = self.localTrajectory(state,wheelbase=0.102/2.0,return_u=True)
        t.e("local traj")
        if retval is None:
            return None,None,False

        # parse return value from localTrajectory
        (local_ctrl_pnt,offset,orientation,curvature,v_target,u0) = retval
        if isnan(orientation):
            return None,None,False

        # calculate s value for projection ref points
        t.s("find s")
        s0 = self.uToS(u0).item()
        v0 = self.targetVfromU(u0%self.track_length_grid).item()
        der = splev(u0%self.track_length_grid,self.raceline,der=1)
        heading0 = atan2(der[1],der[0])
        t.e("find s")

        t.s("curvature")
        _norm = lambda x:np.linalg.norm(x,axis=0)
        # gives right sign for omega, this is indep of track direction since it's calculated based off vehicle orientation

        dr = np.array(splev(u0%self.track_length_grid,self.raceline,der=1))
        ddr = vec_curvature = np.array(splev(u0%self.track_length_grid,self.raceline,der=2))
        cross_curvature = der[0]*vec_curvature[1]-der[1]*vec_curvature[0]
        curvature = 1.0/(_norm(dr)**3/(_norm(dr)**2*_norm(ddr)**2 - np.sum(dr*ddr,axis=0)**2)**0.5)

        t.e("curvature")

        # curvature needs to be signed to indicate whether signage target angular velocity
        # a cross product gives right signage for omega, this is indep of track direction since it's calculated based off vehicle orientation
        cross_curvature = der[0]*vec_curvature[1]-der[1]*vec_curvature[0]

        #k_vec.append(norm_curvature)
        #k_sign_vec.append(cross_curvature)
        k_vec = curvature
        k_sign_vec = cross_curvature


        u_vec = [u0]
        s_vec = [s0]
        k_vec = [curvature]
        k_sign_vec = [cross_curvature]

        v_vec = [v0]
        xy_vec = [splev(s0%self.raceline_len_m, self.raceline_s)]


        t.s("main loop")
        for k in range(1,p+1):
            s_k = s_vec[-1] + v_vec[-1] * dt
            s_vec.append(s_k)
            # find ref velocity for projection ref points
            # TODO adjust ref velocity for current vehicle velocity
            #v_k = self.targetVfromU(u_k%self.track_length_grid)
            #v_k = self.sToV(s_k%self.raceline_len_m)
            v_k = self.sToV_lut(s_k%self.raceline_len_m)
            v_vec.append(v_k)

            xy_vec.append(splev(s_k%self.raceline_len_m, self.raceline_s))
            
        t.e("main loop")

        #u_vec = np.array(u_vec)%self.track_length_grid
        # find ref heading for projection ref points
        t.s("psi")
        #der = np.array(splev(u_vec,self.raceline,der=1))
        s_vec = np.array(s_vec)%self.raceline_len_m
        der = np.array(splev(s_vec,self.raceline_s,der=1))
        heading_vec = np.arctan2(der[1,:],der[0,:])
        t.e("psi")
        # find ref coordinates for projection ref points

        t.s("coord")
        coord_vec = np.array(splev(s_vec,self.raceline_s)).T
        t.e("coord")

        t.s("K")

        #norm_curvature = np.linalg.norm(vec_curvature,axis=1)
        dr = np.array(splev(s_vec,self.raceline_s,der=1))
        ddr = vec_curvature = np.array(splev(s_vec,self.raceline_s,der=2))

        curvature = 1.0/(_norm(dr)**3/(_norm(dr)**2*_norm(ddr)**2 - np.sum(dr*ddr,axis=0)**2)**0.5)

        # curvature needs to be signed to indicate whether signage target angular velocity
        # a cross product gives right signage for omega, this is indep of track direction since it's calculated based off vehicle orientation
        cross_curvature = der[0,:]*vec_curvature[1,:]-der[1,:]*vec_curvature[0,:]

        #k_vec.append(norm_curvature)
        #k_sign_vec.append(cross_curvature)
        k_vec = curvature
        k_sign_vec = cross_curvature




        # TODO check dimension
        k_signed_vec = np.copysign(k_vec,k_sign_vec)

        x,y,heading,vf,vs,omega = state
        e_heading = ((heading - heading0) + pi/2.0 ) % (2*pi) - pi/2.0
        t.e("K")

        t.e()
        return np.array(xy_vec), np.array(v_vec), np.array(heading_vec)
        
    # predict an opponent car's future trajectory, assuming they are on ref raceline and will remain there, traveling at current speed
    # Inputs:
    # state: opponent vehicle state, same as in self.localTrajectory()
    # p : lookahead steps
    # dt : time between each lookahead steps

    # Return:
    # xref : np array of size (p+1)*2, there are p+1 entries because xref0 is the ref point for current location, and then there are p projection points
    # valid : a boolean indicating whether the function was able to find a valid result
    # The function first finds a point on trajectory closest to vehicle location with localTrajectory(), then find p points down the trajectory that are spaced vk * dt apart in path length. vk is the reference velocity at those points

    def predictOpponent(self, state, p, dt, reverse=False):
        if reverse:
            print_error("reverse is not implemented")
        # set wheelbase to 0 to get point closest to vehicle CG
        retval = self.localTrajectory(state,wheelbase=0.102/2.0,return_u=True)
        if retval is None:
            return None,None,False

        # parse return value from localTrajectory
        (local_ctrl_pnt,offset,orientation,curvature,v_target,u0) = retval
        if isnan(orientation):
            return None,None,False

        # calculate s value for projection ref points
        s0 = self.uToS(u0).item()
        # use optimal velocity
        #v0 = self.targetVfromU(u0%self.track_length_grid).item()
        # use actual velocity
        v0 = state[3]

        _norm = lambda x:np.linalg.norm(x,axis=0)

        s_vec = [s0]
        v_vec = [v0]

        for k in range(1,p+1):
            s_k = s_vec[-1] + v_vec[-1] * dt
            s_vec.append(s_k)
            # find ref velocity for projection ref points
            # TODO adjust ref velocity for current vehicle velocity

            #v_k = self.sToV_lut(s_k%self.raceline_len_m)
            # NOTE assume constant velocity
            v_k = v0
            v_vec.append(v_k)

        # find ref heading for projection ref points
        s_vec = np.array(s_vec)%self.raceline_len_m
        # find ref coordinates for projection ref points
        coord_vec = np.array(splev(s_vec,self.raceline_s)).T

        return coord_vec

    # draw a point on canvas at coord
    def drawPoint(self, img, coord, color = (0,0,0)):
        src = self.m2canvas(coord)
        img = cv2.circle(img, src, 3, color,-1)

        return img

    def drawPoints(self, img, coord_vec, color = (0,0,0)):
        for coord in coord_vec:
            src = self.m2canvas(coord)
            img = cv2.circle(img, src, 3, color,-1)

        return img
    
if __name__ == "__main__":
    fulltrack = RCPTrack()
    fulltrack.prepareTrack()

