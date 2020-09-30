# smooth path with quadratic programming
# following paper "A quadratic programming approach to path smoothing"

from RCPTrack import RCPtrack
import numpy as np
import matplotlib.pyplot as plt
from common import *
from math import pi,isclose
import warnings

class QpSmooth:
    # track: RCPtrack object
    def __init__(self,track):
        warnings.simplefilter("error")
        return


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

        al = - sr/sl/(sl-sr)
        a = -(sl+sr)/sl/sr
        ar = -sl/sr/(sr-sl)

        bl = 2/sl/(sl-sr)
        b = 2/sl/sr
        br = 2/sr/(sr-sl)

        return ((al,a,ar),(bl,b,br))

    # construct a fifth order bezier curve passing through endpoints r
    # matching first and second derivative dr, ddr
    # r (2,2)
    # dr (2,2),  taken w.r.t. arc length s
    # ddr (2,2), taken w.r.t. arc length s 
    # ds: arc length between the endpoints
    def bezierCurve(self,r,dr,ddr,ds=None):
        rl,rr = r
        drl,drr = dr
        ddrl,ddrr = ddr

        dist = lambda x,y:((x[0]-y[0])**2 + (x[1]-y[1])**2)**0.5
        if ds is None:
            ds = dist(rl,rr)

        # two sets of equations, one for x, one for y
        #bx = np.matrix([rl[0],rr[0],drl[0],drr[0],ddrl[0],ddrr[0]]).T
        #by = np.matrix([rl[1],rr[1],drl[1],drr[1],ddrl[1],ddrr[1]]).T

        # dr = dr/ds = dr/dt * dt/ds
        # we want dB/dt = dr/dt = dr(input) * ds/dt = dr * ds(between two endpoints)
        bx = np.array([rl[0],rr[0],drl[0]*ds,drr[0]*ds,ddrl[0]*ds*ds,ddrr[0]*ds*ds]).T
        by = np.array([rl[1],rr[1],drl[1]*ds,drr[1]*ds,ddrl[1]*ds*ds,ddrr[1]*ds*ds]).T
        b = np.vstack([bx,by]).T

        # x_x = P0_x, P1_x ... P5_x
        # x_y = P0_y, P1_y ... P5_y
        A = [[ 1, 0, 0, 0, 0, 0],
             [ 0, 0, 0, 0, 0, 1],
             [-5, 5, 0, 0, 0, 0],
             [ 0, 0, 0, 0,-5, 5],
             [20,-40,20,0, 0, 0],
             [0 , 0, 0,20,-40,20]]
        A = np.array(A)

        try:
            sol = np.linalg.solve(A,b)
        except np.linalg.LinAlgError:
            print_error("can't solve bezier Curve")

        # return the control points
        P = sol
        return P

    # generate a bezier spline matching derivative estimated from lagrange interpolation
    # break_pnts.shape = (n,2)
    # return: vector function, domain [0,len(points)]
    def bezierSpline(self,break_pnts):
        break_pnts = np.array(break_pnts).T

        # calculate first and second derivative
        # w.r.t. ds, estimated with 2-norm
        df = []
        ddf = []
        n = break_pnts.shape[1]
        for i in range(n):
            rl = break_pnts[:,(i-1)%n]
            r  = break_pnts[:,(i)%n]
            rr = break_pnts[:,(i+1)%n]
            points = [rl, r, rr]
            
            ((al,a,ar),(bl,b,br)) = self.lagrangeDer(points)
            df.append( al*rl + a*r + ar*rr)
            ddf.append(bl*rl + b*r + br*rr)

        P = []
        for i in range(n):
            # generate bezier spline segments
            rl = break_pnts[:,(i)%n]
            r  = break_pnts[:,(i+1)%n]
            section_P = self.bezierCurve([rl,r],[df[i],df[(i+1)%n]],[ddf[i],ddf[(i+1)%n]],ds=None)
            # NOTE testing
            B = lambda t,p: (1-t)**5*p[0] + 5*t*(1-t)**4*p[1] + 10*t**2*(1-t)**3*p[2] + 10*t**3*(1-t)**2*p[3] + 5*t**4*(1-t)*p[4] + t**5*p[5]
            x_i = B(0,section_P[:,0])
            y_i = B(0,section_P[:,1])
            x_f = B(1,section_P[:,0])
            y_f = B(1,section_P[:,1])
            assert np.isclose(x_i,rl[0],atol=1e-5) and np.isclose(y_i,rl[1],atol=1e-5) and np.isclose(x_f,r[0],atol=1e-5) and np.isclose(y_f,r[1],atol=1e-5)

            P.append(section_P)

        # NOTE verify P dimension n*2*5
        return np.array(P)

    # P: array of control points, shape n*2*5
    # u (iterable): parameter, domain [0,n], where n is number of break points in spline generation

    def evalBezierSpline(self,P,u):
        n = len(P)
        assert (u>=0).all()
        assert (u<=n).all()

        B = lambda t,p: (1-t)**5*p[0] + 5*t*(1-t)**4*p[1] + 10*t**2*(1-t)**3*p[2] + 10*t**3*(1-t)**2*p[3] + 5*t**4*(1-t)*p[4] + t**5*p[5]

        try:
            r = [ [B(uu%1,np.array(P[int(uu)%n,:,0])),B(uu%1,np.array(P[int(uu)%n,:,1]))] for uu in u]
        except Warning as e:
            print(e)

        return np.array(r)


    def testLagrangeDer(self):
        # generate three points
        points = np.array([[-1,-1],[2,2],[5,5]])
        rl,r,rr = points
        ((al,a,ar),(bl,b,br)) = self.lagrangeDer(points)
        df = al*rl + a*r + ar*rr
        ddf = bl*rl + b*r + br*rr
        print(df)
        print(ddf)
        x = points[:,0]
        y = points[:,1]
        plt.plot(x,y)
        plt.show()
        return

    # test bezier curve
    def testBezierCurve(self):
        # generate a batch of points following a unit circle
        u = np.linspace(0,(2*pi)/15.0*14,15)
        xx = np.cos(u)
        yy = np.sin(u)
        points = np.vstack([xx,yy]).T
        points[4,:] = [0,1.2]
        P = self.bezierSpline(points)

        u_close = np.linspace(0,points.shape[0],1000)
        r = self.evalBezierSpline(P,u_close)

        B_x = r[:,0]
        B_y = r[:,1]

        plt.plot(points[:,0],points[:,1],'bo')
        plt.plot(B_x,B_y)

        plt.show()

        return



if __name__ == "__main__":
    qp = QpSmooth(None)
    qp.testBezierCurve()
