from common import *
import serial
from math import atan2,radians,degrees,sin,cos,pi,tan,copysign,asin,acos,isnan,exp,pi
class Car:
    car_count = 0
    cars = []
    # states
    def __init__(self,main):
        self.main = main
        self.controller = None
        self.throttle = 0.0
        self.steering = 0.0
        #x,y,heading,v_forward,v_sideways(left positive),omega(angular speed,turning to left positive)
        self.states = (0,0,0,0,0,0)
        self.debug_dict = {}

    # this function should run without hardware peripherals
    def init(self):
        if (self.main.experiment_type == ExperimentType.Realworld):
            self.initHardware()
        self.wheelbase = self.params['wheelbase']
        self.max_throttle = self.params['max_throttle']
        self.max_steering_left = self.params['max_steer_angle_left']
        self.max_steering_right = self.params['max_steer_angle_right']
        self.max_throttle = self.params['max_throttle']
        self.optitrack_id = self.params['optitrack_streaming_id']
        self.controller.init()

    # initialize code that require hardware here
    def initHardware(self):
        raise NotImplementedError
    def actuate(self):
        raise NotImplementedError

    def control(self):
        if (self.controller is None):
            self.throttle = 0.0
            self.steering = 0.0
        else:
            # TODO: address when controller can't find a valid solution
            self.controller.control()
            #print_info("[Car]: "+"T=%4.1f, S=%4.1f"%(self.throttle, degrees(self.steering)))
            #print_info(self.states)

        if (self.main.slowdown.is_set()):
            self.throttle = 0.0
        if (self.main.experiment_type == ExperimentType.Realworld):
            self.actuate()

    @classmethod
    def reset(cls):
        cls.cars = []
        cls.car_count = 0

    @classmethod
    def Factory(cls, main, config):
        # TODO error handling, it's ok there's no hardware
        hardware_class_text = config.getElementsByTagName('hardware')[0].firstChild.nodeValue
        exec('from car import '+hardware_class_text)

        config_controller = config.getElementsByTagName('controller')[0]
        controller_class_text = config_controller.getElementsByTagName('type')[0].firstChild.nodeValue
        init_states_text = config.getElementsByTagName('init_states')[0].firstChild.nodeValue
        config_name = config.getElementsByTagName('config_name')[0].firstChild.nodeValue
        init_states = eval(init_states_text)
        exec('from controller import '+controller_class_text)
        controller = eval(controller_class_text)
        config_name = config_name

        car = eval(hardware_class_text)(main)

        # (x,y,theta,vforward,vsideway=0,omega)
        x,y,heading,v_forward = init_states
        car.states = (x,y,heading,v_forward,0,0)

        porsche = {'wheelbase':90e-3,
                         'max_steer_angle_left':radians(27.1),
                         'max_steer_pwm_left':1150,
                         'max_steer_angle_right':radians(27.1),
                         'max_steer_pwm_right':1850,
                         'serial_port' : '/dev/ttyUSB0',
                         'optitrack_streaming_id' : 2,
                         #'optitrack_streaming_id' : 998,
                         'max_throttle' : 1.0,
                         'rendering' : 'data/porsche_orange.png'}


        porsche_slow = {'wheelbase':90e-3,
                         'max_steer_angle_left':radians(27.1),
                         'max_steer_pwm_left':1150,
                         'max_steer_angle_right':radians(27.1),
                         'max_steer_pwm_right':1850,
                         'serial_port' : '/dev/ttyUSB0',
                         'optitrack_streaming_id' : 2,
                         #'optitrack_streaming_id' : 998,
                         'max_throttle' : 1.0,
                         'rendering' : 'data/porsche_orange.png'}

        lambo = {'wheelbase':98e-3,
                         'max_steer_angle_left':asin(2*98e-3/0.52),
                         'max_steer_pwm_left':1100,
                         'max_steer_angle_right':asin(2*98e-3/0.47),
                         'max_steer_pwm_right':1850,
                         'serial_port' : '/dev/ttyUSB1',
                         'optitrack_streaming_id' : 15,
                         'max_throttle' : 1.0,
                         'rendering' : 'data/porsche_green.png'}

        # TODO render audi
        audi_11 = {'wheelbase':98e-3,
                         'optitrack_streaming_id' : 15,
                         'ip' : '192.168.0.11',
                         'max_steer_angle_left':radians(26.1),
                         'max_steer_angle_right':radians(26.1),
                         'max_throttle' : 1.0,
                         'rendering' : 'data/porsche_green.png'}

        audi_12 = {'wheelbase':98e-3,
                         'optitrack_streaming_id' : 15,
                         'ip' : '192.168.0.12',
                         'max_steer_angle_left':radians(26.1),
                         'max_steer_angle_right':radians(26.1),
                         'max_throttle' : 1.0,
                         'rendering' : 'data/porsche_green.png'}

        car.params = eval(config_name)
        #print_error("Unrecognized car config")

        if not controller is None:
            car.controller = controller(car,config_controller)

        # default physics properties
        # used when a specific car subclass is not speciied
        car.L = 0.09
        car.lf = 0.04824
        car.lr = car.L - car.lf

        car.Iz = 417757e-9
        car.m = 0.1667
        # ----

        car.id = Car.car_count
        Car.cars.append(car)
        Car.car_count += 1

        return car
