import numpy as np
from common import *
from Extension import Extension

class CollisionChecker(Extension):
    def __init__(self,main):
        Extension.__init__(self,main)
        self.collision_count = [0] * len(self.main.cars)

    def update(self):
        for i in range(len(self.main.cars)):
            car = self.main.cars[i]
            if (car.controller.isInObstacle()):
                self.collision_count[i] += 1
                #print_ok(self.prefix(), "collision = %d"%(self.collision_count))

    def final(self):
        for i in range(len(self.main.cars)):
            print_ok(self.prefix(), "car %d, total collision = %d"%(i,self.collision_count[i]))
        self.main.car_total_collisions = self.collision_count

