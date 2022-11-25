import numpy as np
from common import *
from extension.Extension import Extension

# check collision with static obstacles
class CollisionChecker(Extension):
    def __init__(self,main):
        Extension.__init__(self,main)
        self.collision_count = [0] * len(self.main.cars)
        # collision count by lap
        self.collision_by_lap_vec = [[] * len(self.main.cars)]

    def update(self):
        for i in range(len(self.main.cars)):
            car = self.main.cars[i]
            if (self.main.track.isInObstacle(car.states)[0]):
                self.print_info('collision with obstacle')
                self.collision_count[i] += 1
                car.in_collision = True
                #print_ok(self.prefix(), "collision = %d"%(self.collision_count[i]))
            else:
                car.in_collision = False
            try:
                if (car.laptimer.new_lap.is_set()):
                    self.collision_by_lap_vec[i].append(self.collision_count[i])
                    self.collision_count[i] = 0
            except AttributeError:
                pass

    def final(self):
        total_vec = []
        mean_vec = []
        for i in range(len(self.main.cars)):
            total = np.sum(self.collision_by_lap_vec[i][1:])
            mean = np.mean(self.collision_by_lap_vec[i][1:])
            total_vec.append(total)
            mean_vec.append(mean)
            self.print_info("car %d, total obstacle collision = %d, mean = %.2f"%(i,total, mean))
        self.main.car_total_collisions = total_vec


