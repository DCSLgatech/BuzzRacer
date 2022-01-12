from common import *
from extension import Extension
from time import time,sleep
# base class for all simulators
# contains code for aligning simulator time with real time

# it is required that:
# car.states = x,y,heading,v_forward,v_sideway,omega
# however simulator can establish a property car.sim_states
# that use different state representation
class Simulator(Extension):
    def __init__(self,main):
        super().__init__(main)
        self.match_time = True
        self.t0 = None
        self.real_sim_time_ratio = 1.0
        print_ok(self.prefix() + "real/sim time ratio = %.1f "%(self.real_sim_time_ratio))

    def init(self):
        # ensure experiment_type hasn't been initialized
        flag_is_unique = False
        try:
            self.main.experiment_type != ExperimentType.Simulation
        except (AttributeError):
            flag_is_unique = True
        if (not flag_is_unique):
            print_error(self.prefix() + "another state update source has been initialized")

        self.main.experiment_type = ExperimentType.Simulation
        self.main.sim_t = 0
        print_ok(self.prefix() + "match_time: " + str(self.match_time))

    def matchRealTime(self):
        if (not self.match_time):
            return
        if (self.t0 is None):
            self.t0 = time()
        time_to_reach = self.main.sim_t * self.real_sim_time_ratio + self.t0
        #print("sim_t = %.3f, time = %.3f, expected= %.3f, delta = %.3f"%(self.main.sim_t, time()-self.t0, self.main.sim_t*self.real_sim_time_ratio, time_to_reach-time() ))
        if (time_to_reach-time() < 0):
            pass
            #print_warning("algorithm can't keep up ..... %.3f s"%(time()-time_to_reach))

        sleep(max(0,time_to_reach - time()))

