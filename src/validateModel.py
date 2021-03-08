# visualize model prediction against actual trajectories

import pickle
import matplotlib.pyplot as plt
import numpy as np
import sys
import os
sys.path.append(os.path.abspath('../../src/'))
from common import *
from kalmanFilter import KalmanFilter
from math import pi,degrees,radians,sin,cos,tan,atan
from scipy.signal import savgol_filter

from RCPTrack import RCPtrack
import cv2
from time import sleep

from tire import tireCurve
from PIL import Image


saveGif = False
gifs = []

if (len(sys.argv) != 2):
    filename = "../log/jan3/full_state1.p"
    print_info("using %s"%(filename))
    #print_error("Specify a log to load")
else:
    filename = sys.argv[1]
with open(filename, 'rb') as f:
    data = pickle.load(f)
data = np.array(data)
data = data.squeeze(1)

skip = 1
t = data[skip:,0]
t = t-t[0]
x = data[skip:,1]
y = data[skip:,2]
heading = data[skip:,3]
steering = data[skip:,4]
throttle = data[skip:,5]

dt = 0.01
vx = np.hstack([0,np.diff(x)])/dt
vy = np.hstack([0,np.diff(y)])/dt
omega = np.hstack([0,np.diff(heading)])/dt

# local speed
# forward
vx_car = vx*np.cos(heading) + vy*np.sin(heading)
# lateral, left +
vy_car = -vx*np.sin(heading) + vy*np.cos(heading)

exp_kf_x = data[skip:,6]
exp_kf_y = data[skip:,7]
exp_kf_v = data[skip:,8]
exp_kf_vx = exp_kf_v *np.cos(exp_kf_v)
exp_kf_vy = exp_kf_v *np.sin(exp_kf_v)
exp_kf_theta = data[skip:,9]
exp_kf_omega = data[skip:,10]

'''
# use kalman filter results
x = exp_kf_x
y = exp_kf_y
vx = exp_kf_vx
vy = exp_kf_vy
heading = exp_kf_theta
'''
# NOTE using filtered omega
omega = exp_kf_omega

data_len = t.shape[0]

history_steps = 5
forward_steps = 3

full_state_vec = []

track = RCPtrack()
track.load()

def show(img):
    plt.imshow(img)
    plt.show()
    return

#state: x,vx(global),y,vy,heading,omega
#control: steering(rad),throttle(raw unit -1 ~ 1)
def step_kinematic(state,control,dt=0.01):
    # constants
    L = 0.102
    lr = 0.036
    # convert to local frame
    x,vxg,y,vyg,heading,omega = tuple(state)
    steering,throttle = tuple(control)
    vx = vxg*cos(heading) + vyg*sin(heading)
    vy = -vxg*sin(heading) + vyg*cos(heading)

    # some convenience variables
    R = L/tan(steering)
    beta = atan(lr/R)
    norm = lambda a,b:(a**2+b**2)**0.5

    #advance model
    vx = max(0,vx + (throttle - 0.24)*7.0*dt)
    #vx = vx + (throttle)*7.0*dt
    vy = norm(vx,vy)*sin(beta)
    assert vy*steering>0


    # NOTE where to put this
    omega = vx/R

    # back to global frame
    vxg = vx*cos(heading)-vy*sin(heading)
    vyg = vx*sin(heading)+vy*cos(heading)

    # apply updates
    x += vxg*dt
    y += vyg*dt
    heading += omega*dt

    return (x,vxg,y,vyg,heading,omega ),{}

# old, kinematic model with correction
def step_kinematic_heuristic(state,control,dt=0.01):
    # constants
    L = 0.102
    lr = 0.036
    # convert to local frame
    x,vxg,y,vyg,heading,omega = tuple(state)
    steering,throttle = tuple(control)
    vx = vxg*cos(heading) + vyg*sin(heading)
    vy = -vxg*sin(heading) + vyg*cos(heading)

    # some convenience variables
    R = L/tan(steering)
    beta = atan(lr/R)
    norm = lambda a,b:(a**2+b**2)**0.5

    #advance model
    vx = max(0.0,vx + (throttle - 0.24)*7.0*dt)
    #vx = vx + (throttle)*7.0*dt
    vy = norm(vx,vy)*sin(beta)
    assert vy*steering>0

    # NOTE heuristics
    vy -= 0.68*vx*steering


    # NOTE where to put this
    omega = vx/R

    # back to global frame
    vxg = vx*cos(heading)-vy*sin(heading)
    vyg = vx*sin(heading)+vy*cos(heading)

    # apply updates
    x += vxg*dt
    y += vyg*dt
    heading += omega*dt

    return (x,vxg,y,vyg,heading,omega ),{}

# dynamic model with heuristically selected parameters
def step_dynamics(state,control,dt=0.01):
    # constants
    lf = 0.09-0.036
    lr = 0.036
    # convert to local frame
    x,vxg,y,vyg,heading,omega = tuple(state)
    steering,throttle = tuple(control)
    # forward
    vx = vxg*cos(heading) + vyg*sin(heading)
    # lateral, left +
    vy = -vxg*sin(heading) + vyg*cos(heading)

    # TODO handle vx->0
    # for small velocity, use kinematic model 
    slip_f = -np.arctan((omega*lf + vy)/vx) + steering
    slip_r = np.arctan((omega*lr - vy)/vx)
    # we call these acc but they are forces normalized by mass
    # TODO consider longitudinal load transfer
    lateral_acc_f = tireCurve(slip_f) * 9.8 * lr / (lr + lf)
    lateral_acc_r = tireCurve(slip_r) * 9.8 * lf / (lr + lf)
    # TODO use more comprehensive model
    forward_acc_r = (throttle - 0.24)*7.0

    ax = forward_acc_r - lateral_acc_f * sin(steering) + vy*omega
    ay = lateral_acc_r + lateral_acc_f * cos(steering) - vx*omega

    vx += ax * dt
    vy += ay * dt

    # leading coeff = m/Iz
    d_omega = 12.0/(0.1**2+0.1**2)*(lateral_acc_f * lf * cos(steering) - lateral_acc_r * lr )
    omega += d_omega * dt

    # back to global frame
    vxg = vx*cos(heading)-vy*sin(heading)
    vyg = vx*sin(heading)+vy*cos(heading)

    # apply updates
    # TODO add 1/2 a t2
    x += vxg*dt
    y += vyg*dt
    heading += omega*dt + 0.5* d_omega * dt * dt

    retval = (x,vxg,y,vyg,heading,omega )
    debug_dict = {"slip_f":slip_f, "slip_r":slip_r, "lateral_acc_f":lateral_acc_f, "lateral_acc_r":lateral_acc_r, 'ax':ax}
    return retval, debug_dict

# model with parameter from ukf
def step_ukf(state,control,dt=0.01):
    # constants
    lf = 0.09-0.036
    lr = 0.036
    L = 0.09

    Df = 3.93731
    Dr = 6.23597
    C = 2.80646
    B = 0.51943
    Cm1 = 6.03154
    Cm2 = 0.96769
    Cr = -0.20375
    Cd = 0.00000
    Iz = 0.00278
    m = 0.1667



    # convert to local frame
    x,vxg,y,vyg,heading,omega = tuple(state)
    steering,throttle = tuple(control)
    # forward
    vx = vxg*cos(heading) + vyg*sin(heading)
    # lateral, left +
    vy = -vxg*sin(heading) + vyg*cos(heading)

    # for small velocity, use kinematic model 
    if (vx<0.05):
        beta = atan(lr/L*tan(steering))
        norm = lambda a,b:(a**2+b**2)**0.5
        # motor model
        d_vx = (( Cm1 - Cm2 * vx) * throttle - Cr - Cd * vx * vx)
        vx = vx + d_vx * dt
        vy = norm(vx,vy)*sin(beta)
        d_omega = 0.0
        omega = vx/L*tan(steering)

        slip_f = 0
        slip_r = 0
        Ffy = 0
        Fry = 0

    else:
        slip_f = -np.arctan((omega*lf + vy)/vx) + steering
        slip_r = np.arctan((omega*lr - vy)/vx)

        Ffy = Df * np.sin( C * np.arctan(B *slip_f)) * 9.8 * lr / (lr + lf) * m
        Fry = Dr * np.sin( C * np.arctan(B *slip_r)) * 9.8 * lf / (lr + lf) * m

        # motor model
        Frx = (( Cm1 - Cm2 * vx) * throttle - Cr - Cd * vx * vx)*m

        # Dynamics
        d_vx = 1.0/m * (Frx - Ffy * np.sin( steering ) + m * vy * omega)
        d_vy = 1.0/m * (Fry + Ffy * np.cos( steering ) - m * vx * omega)
        d_omega = 1.0/Iz * (Ffy * lf * np.cos( steering ) - Fry * lr)

        # discretization
        vx = vx + d_vx * dt
        vy = vy + d_vy * dt
        omega = omega + d_omega * dt 

    # back to global frame
    vxg = vx*cos(heading)-vy*sin(heading)
    vyg = vx*sin(heading)+vy*cos(heading)

    # apply updates
    # TODO add 1/2 a t2
    x += vxg*dt
    y += vyg*dt
    heading += omega*dt + 0.5* d_omega * dt * dt

    retval = (x,vxg,y,vyg,heading,omega )
    debug_dict = {"slip_f":slip_f, "slip_r":slip_r, "lateral_acc_f":Ffy/m, "lateral_acc_r":Fry/m, 'ax':d_vx}
    return retval, debug_dict

# model with parameter from ukf
def step_ukf_linear(state,control,dt=0.01):
    # constants
    lf = 0.09-0.036
    lr = 0.036
    L = 0.09

    '''
    Df = 3.93731
    Dr = 6.23597
    C = 2.80646
    B = 0.51943
    '''
    #Cm1 = 6.03154
    Cm2 = 0.96769
    #Cr = -0.20375
    Cm1 = 9.23154
    Cr = 0.0
    Cd = 0.00000
    #Iz = 0.00278
    m = 0.1667
    Iz = m*(0.1**2+0.1**2)/12.0 * 6.0
    K = 5.0



    # convert to local frame
    x,vxg,y,vyg,heading,omega = tuple(state)
    steering,throttle = tuple(control)
    # forward
    vx = vxg*cos(heading) + vyg*sin(heading)
    # lateral, left +
    vy = -vxg*sin(heading) + vyg*cos(heading)

    # for small velocity, use kinematic model 
    if (vx<0.05):
        beta = atan(lr/L*tan(steering))
        norm = lambda a,b:(a**2+b**2)**0.5
        # motor model
        d_vx = (( Cm1 - Cm2 * vx) * throttle - Cr - Cd * vx * vx)
        vx = vx + d_vx * dt
        vy = norm(vx,vy)*sin(beta)
        d_omega = 0.0
        omega = vx/L*tan(steering)

        slip_f = 0
        slip_r = 0
        Ffy = 0
        Fry = 0

    else:
        slip_f = -np.arctan((omega*lf + vy)/vx) + steering
        slip_r = np.arctan((omega*lr - vy)/vx)

        # tire model -- pacejka model
        #Ffy = Df * np.sin( C * np.arctan(B *slip_f)) * 9.8 * lr / (lr + lf) * m
        #Fry = Dr * np.sin( C * np.arctan(B *slip_r)) * 9.8 * lf / (lr + lf) * m

        Ffy = K * slip_f * 9.8 * lr / (lr + lf) * m
        Fry = K * slip_r * 9.8 * lf / (lr + lf) * m

        # motor model
        Frx = (( Cm1 - Cm2 * vx) * throttle - Cr - Cd * vx * vx)*m

        # Dynamics
        d_vx = 1.0/m * (Frx - Ffy * np.sin( steering ) + m * vy * omega)
        d_vy = 1.0/m * (Fry + Ffy * np.cos( steering ) - m * vx * omega)
        d_omega = 1.0/Iz * (Ffy * lf * np.cos( steering ) - Fry * lr)

        # discretization
        vx = vx + d_vx * dt
        vy = vy + d_vy * dt
        omega = omega + d_omega * dt 

    # back to global frame
    vxg = vx*cos(heading)-vy*sin(heading)
    vyg = vx*sin(heading)+vy*cos(heading)

    # apply updates
    # TODO add 1/2 a t2
    x += vxg*dt
    y += vyg*dt
    heading += omega*dt + 0.5* d_omega * dt * dt

    retval = (x,vxg,y,vyg,heading,omega )
    debug_dict = {"slip_f":slip_f, "slip_r":slip_r, "lateral_acc_f":Ffy/m, "lateral_acc_r":Fry/m, 'ax':d_vx}
    return retval, debug_dict

def test():
    img_track = track.drawTrack()
    img_track = track.drawRaceline(img=img_track)
    #img_track = track.drawRaceline(img=img_track)
    cv2.imshow('validate',img_track)
    cv2.waitKey(10)

    sim_steps = 1000
    x = 1.5
    y = 1.6
    vxg = 1.0
    vyg = 0.5
    heading = radians(30)
    omega = 0.0

    steering = radians(25)
    throttle = 0.5


    state =  (x,vxg,y,vyg,heading,omega )
    predicted_states = []

    start = 0
    for i in range(start,start+sim_steps):
        control = (steering,throttle)
        state = step_dynamics(state,control)
        predicted_states.append(state)

        car_state = (state[0],state[2],state[4],0,0,0)
        img = track.drawCar(img_track.copy(), car_state, steering)

        '''
        cv2.imshow('validate',img)
        k = cv2.waitKey(10) & 0xFF
        if k == ord('q'):
            print("halt")
            break
        sleep(0.05)
        '''

    predicted_states = np.array(predicted_states)
    plt.plot(predicted_states[:,0],predicted_states[:,2])
    plt.show()

def run():
    step_fun = step_ukf_linear
    step_fun2 = step_ukf
    #step_fun = step_kinematic_heuristic
    #step_fun = step_kinematic
    '''
    plt.plot(x,y)
    plt.show()

    plt.plot(vx)
    plt.plot(vy)
    plt.show()

    plt.plot(heading)
    plt.show()

    plt.plot(omega)
    plt.show()
    '''


    img_track = track.drawTrack()
    img_track = track.drawRaceline(img=img_track)
    cv2.imshow('validate',img_track)
    cv2.waitKey(10)

    lookahead_steps = 100
    debug_dict_hist = {"slip_f":[[]], "slip_r":[[]], "lateral_acc_f":[[]], "lateral_acc_r":[[]],'ax':[[]]}
    for i in range(1,data_len-lookahead_steps-1):
        # prepare states
        # draw car current pos
        car_state = (x[i],y[i],heading[i],0,0,0)
        img = track.drawCar(img_track.copy(), car_state, steering[i])

        # plot actual future trajectory
        actual_future_traj = np.vstack([x[i:i+lookahead_steps],y[i:i+lookahead_steps]]).T
        img = track.drawPolyline(actual_future_traj,lineColor=(255,0,0),img=img.copy())

        # distance travelled in actual future trajectory
        cum_distance_actual = 0.0
        cum_distance_actual_list = []
        for j in range(i,i+lookahead_steps-1):
            dist = ((x[j+1] - x[j])**2 + (y[j+1] - y[j])**2)**0.5
            cum_distance_actual += dist
            cum_distance_actual_list.append(dist)

        # velocity in horizon
        v_actual_hist = (vx[i:i+lookahead_steps]**2 + vy[i:i+lookahead_steps]**2)**0.5
            
        #show(img)


        '''
        # calculate predicted trajectory -- baseline
        state = (x[i],vx[i],y[i],vy[i],heading[i],omega[i])
        control = (steering[i],throttle[i])
        predicted_states = [state]
        for j in range(i+1,i+lookahead_steps):
            state = step(state,control)
            predicted_states.append(state)
            control = (steering[j],throttle[j])

        predicted_states = np.array(predicted_states)
        predicted_future_traj = np.vstack([predicted_states[:,0],predicted_states[:,2]]).T
        # GREEN
        img = track.drawPolyline(predicted_future_traj,lineColor=(0,255,0),img=img)
        '''

        state = (x[i],vx[i],y[i],vy[i],heading[i],omega[i])
        control = (steering[i],throttle[i])
        predicted_states = [state]
        print("step = %d"%(i))

        # debug_dict_hist is 2 level nested list
        # first dim is time step
        # second is prediction in timestep
        for key in debug_dict_hist:
            debug_dict_hist[key].append([])

        # make prediction from current state
        for j in range(i+1,i+lookahead_steps):
            #print(state)
            state, debug_dict = step_fun(state,control)

            '''
            # NOTE use ground truth in velocity
            # calculate actual velocity in world frame
            # using ground truth in longitudinal vel, estimated value in lateral vel
            vx_car_truth = vx_car[j]
            vy_car_predicted = -state[1]*np.sin(state[4]) + state[3]*np.cos(state[4])

            _vxg = vx_car_truth*cos(state[4])-vy_car_predicted*sin(state[4])
            _vyg = vx_car_truth*sin(state[4])+vy_car_predicted*cos(state[4])

            state = (state[0], _vxg, state[2], _vyg, state[4], state[5])
            '''

            for key in debug_dict:
                value = debug_dict[key]
                debug_dict_hist[key][i].append(value)
            predicted_states.append(state)
            control = (steering[j],throttle[j])
            '''
            if (i % 100 ==0 and j<i+3):
                print(debug_dict['slip_f'])
                print(actual_slip_f[i])
            '''

        predicted_states = np.array(predicted_states)
        predicted_future_traj = np.vstack([predicted_states[:,0],predicted_states[:,2]]).T
        # RED
        img = track.drawPolyline(predicted_future_traj,lineColor=(0,0,255),img=img)

        # distance travelled in predicted future trajectory
        cum_distance_predicted = 0.0
        cum_distance_predicted_list = []

        for j in range(lookahead_steps-1):
            dist = ((predicted_future_traj[j+1,0] - predicted_future_traj[j,0])**2 + (predicted_future_traj[j+1,1] - predicted_future_traj[j,1])**2)**0.5
            cum_distance_predicted += dist
            cum_distance_predicted_list.append(dist)

        # velocity predicted
        v_predicted_hist = (predicted_states[:,1]**2 + predicted_states[:,3]**2)**0.5
        vx_car_predicted_hist = predicted_states[:,1]

        # forward
        vx_car_predicted_hist = predicted_states[:,1]*np.cos(predicted_states[:,4]) + predicted_states[:,3]*np.sin(predicted_states[:,4])
        # lateral, left +
        vy_car_predicted_hist = -predicted_states[:,1]*np.sin(predicted_states[:,4]) + predicted_states[:,3]*np.cos(predicted_states[:,4])

        # heading
        predicted_heading_hist = predicted_states[:,4]

        # position error predicted vs actual
        pos_err = ((predicted_future_traj[:,0] - actual_future_traj[:,0])**2 + (predicted_future_traj[:,1] - actual_future_traj[:,1])**2)**0.5

        # actual slip at front tire
        # NOTE subject to delay etc
        lf = 0.09-0.036
        actual_slip_f = -np.arctan((omega*lf + vy_car)/vx_car) + steering

        '''
        # calculate predicted trajectory -- longer time step
        state = (x[i],vx[i],y[i],vy[i],heading[i],omega[i])
        control = (steering[i],throttle[i])
        predicted_states = [state]
        speedup = 4
        for j in range(i+1,i+lookahead_steps,speedup):
            state = step_new(state,control,dt=0.01*speedup)
            predicted_states.append(state)
            control = (steering[j],throttle[j])

        predicted_states = np.array(predicted_states)
        predicted_future_traj = np.vstack([predicted_states[:,0],predicted_states[:,2]]).T
        # GREEN
        img = track.drawPolyline(predicted_future_traj,lineColor=(0,255,0),img=img)
        '''

        #cv.addWeighted(src1, alpha, src2, beta, 0.0)
        #show(img)

        # add text
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
        img = cv2.putText(img, step_fun.__name__[5:], org, font,
                           fontScale, color, thickness, cv2.LINE_AA)
        cv2.imshow('validate',img)
        k = cv2.waitKey(10) & 0xFF
        if saveGif:
            gifs.append(Image.fromarray(cv2.cvtColor(img.copy(),cv2.COLOR_BGR2RGB)))
        if k == ord('q'):
            print("stopping")
            break

        # periodic debugging plots
        if (i % 100 == 0):
            print("showing heading")
            print("showing velocity (total)")
            print("showing local velocity in car frame")

            wrap = lambda x: np.mod(x + np.pi, 2*np.pi) - np.pi
            ax0 = plt.subplot(411)
            ax0.plot(wrap(predicted_heading_hist)/np.pi*180,label="heading predicted")
            ax0.plot(heading[i:i+lookahead_steps]/np.pi*180,label="actual")
            ax0.legend()

            ax1 = plt.subplot(412)
            ax1.plot(v_predicted_hist,label="v predicted")
            ax1.plot(v_actual_hist,label="actual")
            #ax1.plot(steering[i:i+lookahead_steps],label="steering")

            ax1.legend()

            ax2 = plt.subplot(413)
            ax2.plot(vx_car_predicted_hist,label="car vx predicted")
            ax2.plot(vx_car[i:i+lookahead_steps],label="car vx actual")
            #ax2.plot(vy_car_predicted_hist,'--',label="car vy predicted")
            #ax2.plot(vy_car[i:i+lookahead_steps],'--',label="car vy actual")

            ax2.plot(throttle[i:i+lookahead_steps],label="throttle")
            ax2.plot(debug_dict_hist['ax'][i],'--',label="predicted ax")
            ax2.legend()

            ax3 = plt.subplot(414)
            ax3.plot(debug_dict_hist['slip_f'][i],label="predicted slip front")
            ax3.plot(actual_slip_f[i:i+lookahead_steps],label="actual slip front")
            ax3.legend()

            plt.show()
            #print("breakpoint")

        '''
        print("showing x")
        plt.plot(x[i:i+lookahead_steps],'b--')
        plt.plot(predicted_full_state_vec[:,0],'*')
        plt.show()

        print("showing y")
        plt.plot(y[i:i+lookahead_steps],'b--')
        plt.plot(predicted_full_state_vec[:,2],'*')
        plt.show()

        print("showing vx")
        plt.plot(vx[i:i+lookahead_steps],'b--')
        plt.plot(predicted_full_state_vec[:,1],'*')
        plt.show()

        print("showing vy")
        plt.plot(vy[i:i+lookahead_steps],'b--')
        plt.plot(predicted_full_state_vec[:,3],'*')
        plt.show()

        print("showing heading")
        plt.plot(heading[i:i+lookahead_steps],'b--')
        plt.plot(predicted_full_state_vec[:,4],'*')
        plt.show()

        print("showing omega")
        plt.plot(omega[i:i+lookahead_steps],'b--')
        plt.plot(predicted_full_state_vec[:,5],'*')
        plt.show()
        '''


if __name__=="__main__":
    #test()
    run()
    if saveGif:
        print("saving gif... be patient")
        gif_filename = "validate_model.gif"
        gifs[0].save(fp=gif_filename,format='GIF',append_images=gifs,save_all=True,duration = 20,loop=0)
