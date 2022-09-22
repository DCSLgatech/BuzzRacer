from common import *
from math import isnan,pi,degrees,radians
from controller.CarController import CarController
from controller.PidController import PidController
from planner import Planner

class PurePursuitCarController(CarController):
    def __init__(self, car,config):
        super().__init__(car,config)

        for key,value_text in config.attributes.items():
            setattr(self,key,eval(value_text))
            self.print_info(" controller.",key,'=',value_text)

        # if there's planner set it up
        # TODO put this in a parent class constructor
        try:
            config_planner = config.getElementsByTagName('planner')[0]
            planner_class = eval(config_planner.firstChild.nodeValue)
            self.planner = planner_class(config_planner)
            self.planner.main = self.main
            self.planner.car = self.car
            '''
            self.print_ok("setting planner attributes")
            for key,value_text in config_planner.attributes.items():
                setattr(self.planner,key,eval(value_text))
                self.print_info(" main.",key,'=',value_text)
            '''
            self.planner.init()
        except IndexError as e:
            self.print_info("planner not available")
            self.planner = None

    def init(self):
        CarController.init(self)
        self.debug_dict = {}
        self.max_offset = 0.4

        #speed controller
        P = 5 # to be more aggressive use 15
        I = 0.0 #0.1
        D = 0.4
        dt = self.car.main.dt
        self.throttle_pid = PidController(P,I,D,dt,1,2)

        self.track.prepareDiscretizedRaceline()
        self.track.createBoundary()
        self.discretized_raceline = self.track.discretized_raceline
        self.raceline_left_boundary = self.track.raceline_left_boundary
        self.raceline_right_boundary = self.track.raceline_right_boundary

    def control(self):
        if self.planner is None:
            raceline = self.track.raceline
        # find control point of distance lookahead
        breakpoint()
        # change to local reference frame
        # calculate steering
        # find reference speed
        # calculate throttle





        # inquire information about desired trajectory close to the vehicle
        if self.planner is None:
            retval = track.localTrajectory(self.car.states)
        else:
            self.planner.plan()
            retval = self.planner.localTrajectory(self.car.states)

        if retval is None:
            return (0,0,False,{'offset':0})

        (local_ctrl_pnt,offset,orientation,curvature,v_target) = retval

        v_target = min(v_target, self.max_speed)

        throttle,steering,valid,debug_dict = self.ctrlCar(self.car.states,self.track)

        self.debug_dict = debug_dict
        self.car.debug_dict.update(debug_dict)
        #print("[StanleyCarController]: T= %4.1f, S= %4.1f (deg)"%( throttle,degrees(steering)))
        # if vehicle cross error exceeds maximum allowable error, stop the car
        if (abs(offset) > self.max_offset):
            return (0,0,False,{'offset':offset})
        else:
            # sign convention for offset: negative offset(-) requires left steering(+)
            # this is the convention used in track class, determined arbituarily
            # control logic
            #steering = (orientation-heading) - (offset * self.car.P) - (omega-curvature*vf)*self.car.D
            steering = (orientation-heading) - (offset * self.Pfun(abs(vf)))
            # print("D/P = "+str(abs((omega-curvature*vf)*D/(offset*P))))
            # handle edge case, unwrap ( -355 deg turn -> +5 turn)
            steering = (steering+pi)%(2*pi) -pi
            if (steering>self.car.max_steering_left):
                steering = self.car.max_steering_left
            elif (steering<-self.car.max_steering_right):
                steering = -self.car.max_steering_right
            if (v_override is None):
                throttle = self.calcThrottle(state,v_target)
            else:
                throttle = self.calcThrottle(state,v_override)

            #ret =  (throttle,steering,True,{'offset':offset,'dw':omega-curvature*vf,'vf':vf,'v_target':v_target,'local_ctrl_point':local_ctrl_pnt})
            ret =  (throttle,steering,True,{})

        if (v_override is None):
            throttle = self.calcThrottle(state,v_target)
        else:
            throttle = self.calcThrottle(state,v_override)
        if valid:
            # TODO verify this is limiting
            self.car.throttle = throttle
            self.car.steering = steering
        else:
            self.print_warning(" car %d unable to control", self.car.id)
            self.car.throttle = 0.0
            self.car.steering = 0.0
        #self.predict()
        return valid


    # PID controller for forward velocity
    def calcThrottle(self,state,v_target):
        vf = state[3]
        # PI control for throttle
        acc_target = self.throttle_pid.control(v_target,vf)
        throttle = (acc_target + 1.01294228)/4.95445214 

        return max(min(throttle,self.car.max_throttle),-1)

