from .Car import Car
from common import *
import serial
from math import atan2,radians,degrees,sin,cos,pi,tan,copysign,asin,acos,isnan,exp,pi
class OldOffboard(Car):
    car_count = 0
    cars = []
    # states
    def __init__(self,main):
        self.car_interface = None
        Car.__init__(self,main)

    def init(self):
        # max steering is in radians, for vehicle with ackerman steering (inner wheel steer more than outer)
        # steering angle shoud be calculated by arcsin(wheelbase/turning radius), easily derived from non-slipping bicycle model
        # default values are for the MR03 chassis with Porsche 911 GT3 RS body
        self.serial_port = self.params['serial_port']

        # physics properties
        # Defaults for when a specific car instance is not speciied
        self.L = 0.09
        self.lf = 0.04824
        self.lr = self.L - self.lf

        self.Iz = 417757e-9
        self.m = 0.1667

        self.min_pwm_left = self.params['max_steer_pwm_left']
        self.max_pwm_right = self.params['max_steer_pwm_right']
        Car.init(self)

    def initHardware(self):
        try:
            self.car_interface = serial.Serial(self.serial_port,115200, timeout=0.001,writeTimeout=0)
        except (FileNotFoundError,serial.serialutil.SerialException):
            print_error("[Car]: interface %s not found"%self.serial_port)
            exit(1)

    def actuate(self):
        if not (self.car_interface is None):
            self.car_interface.write((str(self.mapdata(self.steering, self.max_steering_left,-self.max_steering_right,self.min_pwm_left,self.max_pwm_right))+","+str(self.mapdata(self.throttle,-1.0,1.0,1900,1100))+'\n').encode('ascii'))
            return True
        else:
            return False

    # provide direct pwm
    def actuatePWM(self,steeringPWM,throttlePWM):
        if not (self.car_interface is None):
            self.car_interface.write((str(int(steeringPWM))+","+str(int(throttlePWM))+'\n').encode('ascii'))
            return True
        else:
            return False
    def __del__(self):
        if ((not self.serial_port is None) and (not self.car_interface is None) and self.car_interface.is_open):
            self.car_interface.close()
    def mapdata(self,x,a,b,c,d):
        y=(x-a)/(b-a)*(d-c)+c
        return int(y)
