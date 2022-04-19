# MPC based trajectory planner
import matplotlib.pyplot as plt
import numpy as np
from MPC import MPC
from time import time
from math import floor
from itertools import product
import scipy.optimize

class Planner:
    def __init__(self):
        # p: prediction horizon
        #self.p = p = horizon = 50
        self.p = p = horizon = 5
        self.opponent_length = 0.17*2
        self.opponent_width = 0.08*2
        return

    # generate a path
    def genPath(self):
        # create a parametric curve
        x_t_fun = lambda t:t
        y_t_fun = lambda t:np.sin(t)
        t_range = 2*np.pi
        t_vec = np.linspace(0,t_range,1000)

        # given t_start and t_end, calculate the curve length inbetween
        def tToS(t_start,t_end,steps=10):
            t_range = t_end-t_start
            if (t_range < 0):
                return 0
            t = np.linspace(t_start,t_end,steps).flatten()
            s = np.sum(np.sqrt(np.diff(x_t_fun(t))**2 + np.diff(y_t_fun(t))**2))
            return s

        # resample to parameter of curve length r(t) -> r(s)
        self.s_vec = s_vec = np.linspace(0,tToS(0,t_range,steps=10000),1000)
        self.ds = ds = s_vec[1] - s_vec[0]
        t_vec = [0]
        for i in range(s_vec.shape[0]-1):
            t = scipy.optimize.root(lambda m:tToS(t_vec[-1],m)-ds, t_vec[-1])
            t_vec.append(t.x[0])
        x_vec = x_t_fun(t_vec)
        y_vec = y_t_fun(t_vec)
        self.t_vec = np.array(t_vec)

        # curvilinear frame reference curve
        # size: n*2
        self.r = self.ref_path = np.vstack([x_vec,y_vec]).T
        self.dr,self.ddr = self.calcDerivative(self.ref_path)
        self.curvature = self.calcCurvature(self.dr,self.ddr)

        # define track boundary
        # left positive, left negetive
        self.track_width = 0.6
        self.left_limit = np.ones_like(s_vec)*self.track_width/2
        self.right_limit = -np.ones_like(s_vec)*self.track_width/2

        # ccw 90 deg
        A = np.array([[0,-1],[1,0]])
        tangent_dir = (A @ self.dr.T)/np.linalg.norm(self.dr,axis=1)
        self.left_boundary = (tangent_dir * self.left_limit).T + self.ref_path
        self.right_boundary = (tangent_dir * self.right_limit).T + self.ref_path

        self.calcArcLen(self.ref_path)

    # TODO
    # test numerical differentiation with matrix multiplication
    def demoMatrixDiff(self):
        # generate r(s)
        self.genPath()
        # generate n(s), lateral offset
        t = self.t_vec
        A = np.array([[0,-1],[1,0]])
        n = 0.1*np.sin(5*t)
        dn = 0.1*5*np.cos(5*t)
        ddn = -0.1*25*np.sin(5*t)
        dddr = np.vstack([np.zeros_like(t),-np.cos(t)])
        # p(s)
        r = self.r.T
        dr = self.dr.T
        dr_norm = np.linalg.norm(dr,axis=0)
        ddr = self.ddr.T
        ps = r + A @ dr/dr_norm * n
        dps = dr + dn * (A @ dr) + n * (A @ ddr)
        I = np.eye(2)
        ddps = ddr + ddn * (A @ dr) + dn *(A @ ddr) + dn * (A @ ddr) + n * (A @ dddr)

        p = self.p

        r = self.r[250:250+p,:]
        dr = self.dr[250:250+p,:]
        r_vec = r.flatten()
        ddr = self.ddr[250:250+p,:]
        n = n[250:250+p]
        dn = dn[250:250+p]
        ddn = ddn[250:250+p]


        # test first derivative
        M1 = planner.getDiff1Matrix(p,self.ds)
        M1 = np.kron(M1,np.eye(2))
        # let s_k be first p elements from self.s_vec
        # select {r_k}
        test_dr = M1 @ r_vec
        test_dr = test_dr.reshape((p,2))
        print("M1 result err")
        print(dr - test_dr)
        # SUCCESS !

        # test second derivative
        M2 = planner.getDiff2Matrix(p,self.ds)
        M2 = np.kron(M2,np.eye(2))
        # let s_k be first p elements from self.s_vec
        # select {r_k}
        test_ddr = M2 @ r_vec
        test_ddr = test_ddr.reshape((p,2))
        print("M2 result err")
        print(ddr - test_ddr)
        # first and last value should be different as ddr from self.lagrangeDer() is not done correctly
        # SUCCESS

        # test matrix representation for cross product
        r1 = np.array([[6,5]]).T
        r2 = np.array([[3,7]]).T
        c1 = np.cross(r1,r2,axisa=0,axisb=0)
        c2 = (A @ r1).T @ r2
        print(c1)
        print(c2)
        # SUCCESS

        # test p'
        I_p = np.eye(p)
        # FIXME this is wrong TODO
        dp = r.flatten() + np.kron(I_p,np.array([[1,1]]).T) @ n @ np.kron(I_p,A) @ dr.flatten()


        breakpoint()




    # demonstrate curvature calculation, verify with inscribe circle
    def demoCurvature(self):
        # define reference path
        # r = <t, sin(t)>
        # r' = <1, cos(t)>
        # r'' = <0, -sin(t)>
        t = np.linspace(0,2*np.pi,1000)
        r = np.vstack([t,np.sin(t)])
        dr = np.vstack([np.ones_like(t),np.cos(t)])
        ddr = np.vstack([np.zeros_like(t),-np.sin(t)])
        dddr = np.vstack([np.zeros_like(t),-np.cos(t)])
        # alternative reference path
        #t = np.linspace(0,6,101)
        #r = np.vstack([3*t**3+4*t,6*t**2+10])
        #dr = np.vstack([9*t**2+4,12*t])
        #ddr = np.vstack([18*t,12*np.ones_like(t)])

        # calculate curvature for r(t)
        k_r = np.cross(dr.T,ddr.T) / np.linalg.norm(dr,axis=0)**3

        # plot tangent circle
        idx = 250
        # ccw 90 deg
        A = np.array([[0,-1],[1,0]])
        radius = 1/k_r[idx]
        center = r[:,idx] + A @ dr[:,idx]/np.linalg.norm(dr[:,idx]) * radius
        theta = np.linspace(0,np.pi*2,1000)
        circle_x = np.cos(theta)*radius + center[0]
        circle_y = np.sin(theta)*radius + center[1]
        # plotting
        '''
        plt.plot(r[0,:],r[1,:])
        plt.plot(circle_x,circle_y)
        plt.plot(r[0,idx],r[1,idx],'*')
        plt.axis('equal')
        plt.show()
        '''

        # curvature for general path p(t)
        n = 0.1*np.sin(5*t)
        dn = 0.1*5*np.cos(5*t)
        ddn = -0.1*25*np.sin(5*t)
        dr_norm = np.linalg.norm(dr,axis=0)
        p = r + A @ dr/dr_norm * n
        dp_alt = np.diff(p) / (t[1]-t[0])
        dp = dr + dn * (A @ dr) + n * (A @ ddr)
        I = np.eye(2)
        ddp = ddr + ddn * (A @ dr) + dn *(A @ ddr) + dn * (A @ ddr) + n * (A @ dddr)
        # safe to drop third derivative
        #ddp = ddr + ddn * (A @ dr) + dn *(A @ ddr) + dn * (A @ ddr)
        # calculate curvature for r(t)
        #k_p = np.cross(dp.T,ddp.T) / np.linalg.norm(dp,axis=0)**3
        # approximate with constant dr
        k_p = np.cross(dp.T,ddp.T) / np.linalg.norm(dr,axis=0)**3

        # plot tangent circle
        idx = 350
        # ccw 90 deg
        A = np.array([[0,-1],[1,0]])
        radius = 1/k_p[idx]
        center = p[:,idx] + A @ dp[:,idx]/np.linalg.norm(dp[:,idx]) * radius
        theta = np.linspace(0,np.pi*2,1000)
        circle_x = np.cos(theta)*radius + center[0]
        circle_y = np.sin(theta)*radius + center[1]

        tangent = p[:,idx] + dp[:,idx]/np.linalg.norm(dp[:,idx])
        normal = p[:,idx] + A @ dp[:,idx]/np.linalg.norm(dp[:,idx])

        plt.plot(r[0,:],r[1,:])
        plt.plot(p[0,:],p[1,:])
        plt.plot(circle_x,circle_y)
        plt.plot(p[0,idx],p[1,idx],'*')
        plt.plot([p[0,idx],tangent[0]],[p[1,idx],tangent[1]])
        plt.plot([p[0,idx],normal[0]],[p[1,idx],normal[1]])
        plt.plot([p[0,idx],center[0]],[p[1,idx],center[1]])
        plt.axis('equal')
        plt.show()

    # control with state = [s,n,ds]
    def demoSingleControl(self):
        # state x:[s,n,ds]
        # u: [dn] first derivative of n
        self.n = n = 3
        self.m = m = 1

        # m/s
        ds = 1.2
        x0 = [1,0.15,ds]
        xref = [7,-0.15,ds]
        # opponents, static, [s,n]
        opponent_state_vec = [[3,0],[5,-0.1]]

        self.genPath()
        sols = self.solveSingleControl(x0,xref,opponent_state_vec)

        self.plotTrack()
        # initial state
        self.plotCar(x0)
        # target state
        self.plotCar(xref)
        for (u_vec, state_traj) in sols:
            self.plotStateTraj(state_traj)
        for opponent in opponent_state_vec:
            self.plotOpponent(opponent)
        plt.axis('equal')
        plt.show()
        breakpoint()

    def getCurvatureObjective(self):
        # find r, dr, ddr
        s = self.s_vec
        r = self.ref_path
        dr = self.dr
        ddr = self.ddr
        # find n, dn, ddn
        #print(np.linalg.norm(dr,axis=0))
        dr = np.linalg.norm(np.diff(r,axis=0),axis=1)
        breakpoint()

        return


    def solveSingleControl(self,x0,xref,opponent_state):
        mpc = MPC()
        self.mpc = mpc
        n = self.n
        m = self.m
        p = self.p
        # setup mpc 
        mpc.setup(n,m,n,p)
        dt = self.dt = 0.1
        A = np.eye(n)
        A[0,2] = dt
        B = np.array([[0,1,0]]).T*dt
        P = np.diag([1,1,0])
        Q = np.eye(m)*5.0

        t = time()
        x0 = np.array(x0).T.reshape(-1,1)
        self.x0 = x0
        xref = np.array(xref).T.reshape(-1,1)
        xref_vec = xref.repeat(p,1).T.reshape(p,n,1)
        #du_max = np.array([[1,1]]).T
        du_max = None
        #u_max = np.array([[1.5,1.5]]).T
        u_max = None
        mpc.convertLtiPlanner(A,B,P,Q,xref_vec,x0,p,u_max,du_max)
        # add track boundary constraints
        self.constructTrackBoundaryConstraint(mpc)
        scenarios = self.constructOpponentConstraint(mpc,opponent_state)
        self.scenarios = scenarios
        sols = []
        # save current mpc matrices
        # solve for different scenarios
        P = mpc.P
        q = mpc.q
        G = mpc.G
        h = mpc.h
        for case in scenarios:
            mpc.P = P
            mpc.q = q
            mpc.G = np.vstack([G,case[0]])
            mpc.h = np.vstack([h,case[1]])
            dt = time()-t
            mpc.solve()
            if (mpc.h is not None):
                print(mpc.h.shape)
            print("freq = %.2fHz"%(1/dt))
            # state_traj in curvilinear frame
            state_traj = mpc.F @ mpc.u + mpc.Ex0
            state_traj = state_traj.reshape((p,n))
            state_traj = np.vstack([x0.T,state_traj])
            sols.append( (mpc.u,state_traj) )

        '''
        plt.plot(state_traj)
        plt.show()
        u = np.array(mpc.u).reshape((-1,2))
        plt.plot(u)
        plt.show()
        '''
        return sols

    # construct the state limits
    def constructTrackBoundaryConstraint(self,mpc):
        # create additional lines for Gx<h
        # track boundary limits
        p = self.p
        if (self.n==4):
            M = np.kron(np.eye(p),np.array([[0,1,0,0]]))
        elif (self.n==3):
            M = np.kron(np.eye(p),np.array([[0,1,0]]))
        elif (self.n==2):
            M = np.kron(np.eye(p),np.array([[0,1]]))
        G1 = M @ mpc.F
        N = np.ones((p,1))*self.track_width/2
        h1 = N - M @ mpc.Ex0

        G2 = -M @ mpc.F
        h2 = N + M @ mpc.Ex0

        if (mpc.G is None):
            mpc.G = np.vstack([G1,G2])
            mpc.h = np.vstack([h1,h2])
        else:
            mpc.G = np.vstack([mpc.G,G1,G2])
            mpc.h = np.vstack([mpc.h,h1,h2])
        return

    def constructOpponentConstraint(self,mpc,opponent_state):
        # TODO quick check feasibility
        # additional constraints to add
        # (G,h)
        # opponent_count * feasible_direction_count
        # one sublist for each opponent
        # sublist contains a set of OR constraints
        # solution need to satisfy ONE constraint from sublist 0, ONE constraint from sublist 1 ...
        opponent_constraints = []
        opponent_idx = 0
        for opponent in opponent_state:
            opponent_constraints.append([])
            # treat opponent as a single point
            idx = self.getIndex(opponent[0])
            # +
            left = self.left_limit[idx]
            # -
            right = self.right_limit[idx]
            # which time step to apply constraints
            step = (opponent[0] - self.x0[0])/self.x0[2]/self.dt
            step_begin = floor(step)
            step_end = step_begin+1
            if (left > opponent[1]+self.opponent_width/2):
                # there's space in left for passing
                left_bound = opponent[1]+self.opponent_width/2
                G1,h1 = self.getGhForN(step_begin,left_bound,False)
                G2,h2 = self.getGhForN(step_end,left_bound,False)
                G = np.vstack([G1,G2])
                h = np.vstack([h1,h2])
                opponent_constraints[-1].append((G,h))
                print("feasible path, oppo %d, left, step %d-%d, n > %.2f"%(opponent_idx, step_begin, step_end,left_bound))
                
            if (right < opponent[1]-self.opponent_width/2):
                # there's space in right for passing
                right_bound = opponent[1]-self.opponent_width/2
                G1,h1 = self.getGhForN(step_begin,right_bound,True)
                G2,h2 = self.getGhForN(step_end,right_bound,True)
                G = np.vstack([G1,G2])
                h = np.vstack([h1,h2])
                opponent_constraints[-1].append((G,h))
                print("feasible path, oppo %d, right, step %d-%d, n < %.2f"%(opponent_idx, step_begin, step_end,right_bound))
            opponent_idx += 1

        # possible combination of AND constraints
        # e.g. opponent 0 can be passed on left or right
        #      opponent 1 can be passed on left 
        # 2 scenarios, (left,left) (left,right)
        cons_combination = [ cons for cons in product(*opponent_constraints)]

        scenarios = [ (np.vstack( [con[0] for con in cons] ), np.vstack( [con[1] for con in cons] )) for cons in product(*opponent_constraints)]
            
        return scenarios

    # get the constraint matrix G h for a single n constraint
    def getGhForN(self,step,val,is_max_constrain):
        mpc = self.mpc
        idx = step*self.n + 1
        M = np.zeros(self.p*self.n)
        M[idx] = 1
        if (is_max_constrain):
            G = M @ mpc.F
            h = val - M @ mpc.Ex0
        else:
            G = -M @ mpc.F
            h = -val + M @ mpc.Ex0
        return (G,h)

    def calcDerivative(self,curve):
        # find first and second derivative
        dr = []
        ddr = []
        n = curve.shape[0]
        ds = self.s_vec[1]-self.s_vec[0]
        for i in range(1,n-1):
            rl = self.ref_path[i-1,:]
            r = self.ref_path[i,:]
            rr = self.ref_path[i+1,:]
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
        curvature = np.dot( (A @ dr_vec.T).T, ddr_vec.T).flatten()
        return curvature

    # calculate segment cumulative length
    def calcArcLen(self,path):
        dr = np.vstack([np.zeros((1,2)),np.diff(path, axis=0)])
        ds = np.linalg.norm(dr,axis=1)
        self.ref_path_s = np.cumsum(ds)

    def stateTrajToCartesianTraj(self,traj):
        cartesian_traj = []
        A = np.array([[0,-1],[1,0]])
        for i in range(traj.shape[0]):
            idx = np.searchsorted(self.ref_path_s,traj[i,0],side='left')
            xy = self.ref_path[idx] + A @ self.dr[idx] * traj[i,1]
            cartesian_traj.append(xy)
        return np.array(cartesian_traj)

    def plotStateTraj(self,traj):
        traj = self.stateTrajToCartesianTraj(traj)
        plt.plot(traj[:,0],traj[:,1])
        return

    def plotTrack(self):
        # get left boundary
        plt.plot(self.ref_path[:,0],self.ref_path[:,1],'--')
        plt.plot(self.left_boundary[:,0],self.left_boundary[:,1],'-')
        plt.plot(self.right_boundary[:,0],self.right_boundary[:,1],'-')

    # given state x =[s,n,ds,dn]
    # plot a dot where the car should be
    def plotCar(self,x):
        # ccw 90 deg
        A = np.array([[0,-1],[1,0]])
        idx = self.getIndex(x[0])
        car_pos = self.ref_path[idx] + A @ self.dr[idx] * x[1]
        plt.plot(car_pos[0],car_pos[1],'o')

    def plotOpponent(self,opponent_state):
        sn = opponent_state
        # left
        s_range = np.linspace(sn[0]-self.opponent_length/2,sn[0]+self.opponent_length/2,10)
        n_range = np.ones_like(s_range)*(sn[1]+self.opponent_width/2)
        traj = np.vstack([s_range,n_range]).T
        traj = self.stateTrajToCartesianTraj(traj)
        plt.plot(traj[:,0],traj[:,1],'b-')
        # right
        n_range = np.ones_like(s_range)*(sn[1]-self.opponent_width/2)
        traj = np.vstack([s_range,n_range]).T
        traj = self.stateTrajToCartesianTraj(traj)
        plt.plot(traj[:,0],traj[:,1],'b-')
        # rear
        n_range = np.linspace((sn[1]-self.opponent_width/2),(sn[1]+self.opponent_width/2),10)
        s_range = np.ones_like(n_range)*(sn[0]-self.opponent_length/2)
        traj = np.vstack([s_range,n_range]).T
        traj = self.stateTrajToCartesianTraj(traj)
        plt.plot(traj[:,0],traj[:,1],'b-')
        # front
        n_range = np.linspace((sn[1]-self.opponent_width/2),(sn[1]+self.opponent_width/2),10)
        s_range = np.ones_like(n_range)*(sn[0]+self.opponent_length/2)
        traj = np.vstack([s_range,n_range]).T
        traj = self.stateTrajToCartesianTraj(traj)
        plt.plot(traj[:,0],traj[:,1],'b-')

    def getIndex(self,s):
        idx = np.searchsorted(self.ref_path_s,s,side='left')
        return idx

    # first order numerical differentiation matrix
    # M1: (p,p)
    # r' = M1 @ r, r = [r_1,r_2,...r_k], r_k = r(s_k), ds = s_{k+1}-s_k
    def getDiff1Matrix(self,p,ds):
        I_p_2 = np.eye(p-2)
        middle_1 = np.hstack([-I_p_2,np.zeros((p-2,2))])
        middle_2 = np.hstack([np.zeros((p-2,2)),I_p_2])
        top = np.zeros((1,p))
        top[0,0] = -3
        top[0,1] = 4
        top[0,2] = -1
        bottom = np.zeros((1,p))
        bottom[0,-1] = 3
        bottom[0,-2] = -4
        bottom[0,-3] = 1
        M1 = np.vstack([top,middle_1+middle_2,bottom])/(2.0*ds)
        return M1

    # second order numerical differentiation matrix
    # M2: (p,p)
    # r' = M2 @ r, r = [r_1,r_2,...r_k], r_k = r(s_k), ds = s_{k+1}-s_k
    def getDiff2Matrix(self,p,ds):
        I_p_2 = np.eye(p-2)
        middle_1 = np.hstack([I_p_2,np.zeros((p-2,2))])
        middle_2 = np.hstack([np.zeros((p-2,1)),-2*I_p_2,np.zeros((p-2,1))])
        middle_3 = np.hstack([np.zeros((p-2,2)),I_p_2])
        middle = (middle_1+middle_2+middle_3) / (ds**2)
        top = np.zeros((1,p))
        top[0,0] = 2
        top[0,1] = -5
        top[0,2] = 4
        top[0,3] = -1
        top = top/(ds**3)
        bottom = np.zeros((1,p))
        bottom[0,-1] = 2
        bottom[0,-2] = -5
        bottom[0,-3] = 4
        bottom[0,-4] = -1
        bottom = bottom/(ds**3)
        M2 = np.vstack([top,middle,bottom])
        return M2

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
if __name__=='__main__':
    planner = Planner()
    planner.demoMatrixDiff()
    #planner.genPath()
    #planner.getCurvatureObjective()
    #planner.demoSingleControl()
    #planner.demoCurvature()
