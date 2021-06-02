import os
import sys
import numpy as np
from time import sleep,time
from math import sin,radians,degrees,ceil,isnan
import matplotlib.pyplot as plt
from timeUtil import execution_timer
base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../')
sys.path.append(base_dir)
from common import *
# Covariance Control - Model Predictive Path Integral

from ccmppi_kinematic import CCMPPI_KINEMATIC

class CCMPPI:
    def __init__(self,samples_count, horizon_steps, state_dim, control_dim, temperature,dt,noise_cov,discretized_raceline,cuda=False,cuda_filename=None):
        self.cc = CCMPPI_KINEMATIC(horizon_steps)
        self.K = samples_count

        self.N = self.T = horizon_steps
        self.m = control_dim
        self.n = self.state_dim = state_dim
        self.temperature = float(temperature)
        self.dt = dt
        # variation of noise added to ref control
        self.noise_cov = noise_cov
        self.p = execution_timer(True)
        # whether to use cuda
        self.cuda = cuda

        self.old_ref_control = np.zeros([self.T,self.m],dtype=np.float32)
        if cuda:
            self.curand_kernel_n = 1024
            print_info("loading cuda module ...")
            import pycuda.autoinit
            global drv
            import pycuda.driver as drv
            from pycuda.compiler import SourceModule
            if cuda_filename is None:
                cuda_filename = "./ccmppi.cu"
            with open(cuda_filename,"r") as f:
                code = f.read()

            # prepare constants
            cuda_code_macros = {"SAMPLE_COUNT":self.K, "HORIZON":self.T, "CONTROL_DIM":self.m,"STATE_DIM":self.state_dim,"RACELINE_LEN":discretized_raceline.shape[0],"TEMPERATURE":self.temperature,"DT":dt}
            # add curand related config
            # new feature for Python 3.9
            #cuda_code_macros = cuda_code_macros | {"CURAND_KERNEL_N":self.curand_kernel_n}
            cuda_code_macros.update({"CURAND_KERNEL_N":self.curand_kernel_n})

            mod = SourceModule(code % cuda_code_macros, no_extern_c=True)

            if (self.K < 1024):
                # if K is small only employ one grid
                self.cuda_block_size = (self.K,1,1)
                self.cuda_grid_size = (1,1)
            else:
                # employ multiple grid,
                self.cuda_block_size = (1024,1,1)
                self.cuda_grid_size = (ceil(self.K/1024.0),1)
            print("cuda block size %d, grid size %d"%(self.cuda_block_size[0],self.cuda_grid_size[0]))

            self.cuda_init_curand_kernel = mod.get_function("init_curand_kernel")
            self.cuda_generate_random_var = mod.get_function("generate_random_normal")
            self.cuda_evaluate_control_sequence = mod.get_function("evaluate_control_sequence")

            seed = np.int32(int(time()*10000))
            self.cuda_init_curand_kernel(seed,block=(1024,1,1),grid=(1,1,1))

            #device_rand_vals = gpuarray.zeros(K*T*m, dtype=np.float32)
            self.rand_vals = np.zeros(self.K*self.T*self.m, dtype=np.float32)
            self.device_rand_vals = drv.to_device(self.rand_vals)

            print_info("registers used each kernel in eval_ctrl= %d"%self.cuda_evaluate_control_sequence.num_regs)
            assert int(self.cuda_evaluate_control_sequence.num_regs * self.cuda_block_size[0]) <= 65536
            assert int(self.cuda_init_curand_kernel.num_regs * self.cuda_block_size[0]) <= 65536
            assert int(self.cuda_generate_random_var.num_regs * self.cuda_block_size[0]) <= 65536

            self.discretized_raceline = discretized_raceline.astype(np.float32)
            self.discretized_raceline = self.discretized_raceline.flatten()
            self.device_discretized_raceline = drv.to_device(self.discretized_raceline)

            sleep(1)

        return

    # given state, apply CCMPPI and find control
    # state: current plant state
    # safety_margin: distance to keep from opponent
    # control_limit: min,max for each control element dim self.m*2 (min,max)
    # control_cov: covariance matrix for noise added to ref_control
    # specifically for racecar
    def control(self,state,control_limit,safety_margin=0.1,noise_cov=None,cuda=None):
        if noise_cov is None:
            noise_cov = self.noise_cov
        if cuda is None:
            cuda = self.cuda
        p = self.p
        p.s()

        # start from zero 
        #ref_control = np.zeros([self.T,self.m])
        #ref_control = self.old_ref_control
        # or, recycle last reference control
        ref_control = np.vstack([self.old_ref_control[1:,:],np.zeros([1,self.m],dtype=np.float32)])

        # CCMPPI specific, generate and pack K matrices
        # NOTE check dimension
        Ks, As, Bs, ds = self.cc.cc(state)

        Ks_flat = np.array(Ks,dtype=np.float32).flatten()
        device_Ks = drv.to_device(Ks_flat)

        As_flat = np.array(As,dtype=np.float32).flatten()
        device_As = drv.to_device(As_flat)

        Bs_flat = np.array(Bs,dtype=np.float32).flatten()
        device_Bs = drv.to_device(Bs_flat)

        '''
        ds_flat = np.array(ds,dtype=np.float32).flatten()
        device_ds = drv.to_device(ds_flat)
        '''

        # NOTE check dimension and unraveling for k

        if (cuda):
            # CUDA implementation
            p.s("prep ref ctrl")
            # assemble limites
            #limits = np.array([-1,1,-2,2],dtype=np.float32)
            control_limit = np.array(control_limit,dtype=np.float32).flatten()
            device_control_limits = drv.to_device(control_limit)

            scales = np.array([np.sqrt(noise_cov[0,0]),np.sqrt(noise_cov[1,1])],dtype=np.float32)
            device_scales = drv.to_device(scales)

            self.cuda_generate_random_var(self.device_rand_vals,device_scales,block=(self.curand_kernel_n,1,1),grid=(1,1,1))

            p.e("prep ref ctrl")

            p.s("cuda sim")
            cost = np.zeros([self.K]).astype(np.float32)
            control = np.zeros(self.K*self.N*self.m).astype(np.float32)

            # we leave the entry point in api for possible future modification
            x0 = state.copy()
            x0 = x0.astype(np.float32)
            # reference control, in standard mppi this should be zero
            ref_control = ref_control.astype(np.float32)
            ref_control = ref_control.flatten()

            # FIXME need update
            memCount = cost.size*cost.itemsize + control.size*control.itemsize + x0.size*x0.itemsize + ref_control.size*ref_control.itemsize + self.rand_vals.size*self.rand_vals.itemsize 
            assert np.sum(memCount)<8370061312


            self.cuda_evaluate_control_sequence( 
                    drv.Out(cost), # size: K
                    drv.Out(control), # output control size:(K*N*m)
                    drv.In(x0),
                    drv.In(ref_control),
                    device_control_limits, 
                    self.device_rand_vals,
                    self.device_discretized_raceline, 
                    device_Ks, device_As, device_Bs,
                    block=self.cuda_block_size, grid=self.cuda_grid_size
                    )


            # NOTE rand_vals is updated to respect control limits
            #self.rand_vals = drv.from_device(self.device_rand_vals,shape=(self.K*self.T*self.m,), dtype=np.float32)
            p.e("cuda sim")
        else:
            print_error("cpu implementation of CCMPPI is unavailable")

        p.s("post")
        # Calculate statistics of cost function
        cost = np.array(cost)
        beta = np.min(cost)

        # calculate weights
        weights = np.exp(- (cost - beta)/self.temperature)
        weights = weights / np.sum(weights)
        #print("best cost %.2f, max weight %.2f"%(beta,np.max(weights)))

        # synthesize control signal
        #self.rand_vals = self.rand_vals.reshape([self.K,self.T,self.m])
        # NOTE test me
        ref_control = ref_control.reshape([self.T,self.m])
        control = control.reshape([self.K, self.N, self.m])
        for t in range(self.T):
            for i in range(self.m):
                # control: (rollout, timestep, control_var)
                ref_control[t,i] =  np.sum(weights * control[:,t,i])
        self.old_ref_control = ref_control.copy()
        p.e("post")

        # evaluate performance of synthesized control
        #print("best cost in sampled traj   %.2f"%(beta))
        #print("worst cost in sampled traj   %.2f"%(np.max(cost)))
        #print("avg cost in sampled traj    %.2f"%(np.mean(cost)))
        #print_info("cost of synthesized control %.2f"%(self.evalControl(state,ref_control)))
        #print("cost of ref control %.2f"%(self.evalControl(state,old_ref_control)))
        #print("cost of no control(0) %.2f"%(self.evalControl(state,old_ref_control)))
        #print("cost of const control(-5 deg) %.2f"%(self.evalControl(state,[[0,-radians(5)]]*self.T)))
        #print("cost of const control(5 deg) %.2f"%(self.evalControl(state,[[0,radians(5)]]*self.T)))

        #return ref_control[0]
        p.e()
        if isnan(ref_control[0,1]):
            print("error")
        return ref_control

    # given state, apply MPPI and find control
    # state: current plant state
    # ref_control: reference control, dim (self.T,self.m)
    # control_limit: min,max for each control element dim self.m*2 (min,max)
    # control_cov: covariance matrix for noise added to ref_control
    # NOTE not up to date
    def control_goal_state(self,target_state,state,ref_control,control_limit,noise_cov=None,cuda=None):
        if noise_cov is None:
            noise_cov = self.noise_cov
        if cuda is None:
            cuda = self.cuda
        p = self.p
        p.s()
        p.s("prep")
        ref_control = np.array(ref_control).reshape(-1,self.m).astype(np.float32)
        control_limit = np.array(control_limit)

        # generate random noise for control sampling
        epsilon_vec = np.random.multivariate_normal([0.0]*self.m, noise_cov, size=(self.K,self.T))

        # assemble control, ref_control is broadcasted along axis 0 (K)
        control_vec = ref_control + epsilon_vec

        # cap control
        for i in range(self.m):
            control_vec[:,i] = np.clip(control_vec[:,i],control_limit[i,0],control_limit[i,1])

        # NOTE which is better
        clipped_epsilon_vec = control_vec - ref_control
        #clipped_epsilon_vec = epsilon_vec


        # for use in epsilon induced cost
        #control_cost_mtx_inv = np.linalg.inv(noise_cov)
        #control_cost_mtx_inv = np.eye(self.m)
        p.e("prep")

        if (cuda):
            # NVIDIA YES !!!
            # CUDA implementation
            p.s("cuda sim")
            cost = np.zeros([self.K]).astype(np.float32)
            epsilon = clipped_epsilon_vec.astype(np.float32)
            control = control_vec.astype(np.float32)
            x0 = state.copy()
            x_goal = target_state.astype(np.float32)
            control = control.flatten()
            memCount = cost.size*cost.itemsize + x0.size*x0.itemsize + control.size*control.itemsize + epsilon*epsilon.itemsize
            assert np.sum(memCount)<8370061312
            self.cuda_evaluate_control_sequence( 
                    drv.Out(cost),drv.In(x_goal),drv.In(x0),drv.In(control), drv.In(epsilon),
                    block=(self.K,1,1), grid=(1,1))
            S_vec = cost
            p.e("cuda sim")
        else:
            p.s("cpu sim")
            # cost value for each simulation
            S_vec = []
            # spawn k simulations
            for k in range(self.K):
                S = 0
                x = state.copy()
                # run each simulation for self.T timesteps
                for t in range(self.T):
                    control = control_vec[k,t,:]
                    x = self.applyDiscreteDynamics(x,control,self.dt)
                    # NOTE ignoring additional epsilon induced cost
                    #S += self.evaluateStepCost(x) + self.temperature * ref_control[t,:].T @ control_cost_mtx_inv @ epsilon_vec[k,t]
                    # FIXME ignoring additional cost
                    S += self.evaluateStepCost(x,control) 
                # NOTE ignoring terminal cost
                #S += self.evaluateTerminalCost(x,x0)
                S_vec.append(S)
            p.e("cpu sim")

        p.s("post")
        # Calculate statistics of cost function
        S_vec = np.array(S_vec)
        beta = np.min(S_vec)

        # calculate weights
        weights = np.exp(- (S_vec - beta)/self.temperature)
        weights = weights / np.sum(weights)


        # synthesize control signal
        old_ref_control = ref_control.copy()
        for t in range(self.T):
            for i in range(self.m):
                ref_control[t,i] = ref_control[t,i] + np.sum(weights * clipped_epsilon_vec[:,t,i])
        p.s("post")


        # evaluate performance of synthesized control
        '''
        print("best cost in sampled traj   %.2f"%(beta))
        print("worst cost in sampled traj   %.2f"%(np.max(S_vec)))
        print("avg cost in sampled traj    %.2f"%(np.mean(S_vec)))
        print_info("cost of synthesized control %.2f"%(self.evalControl(state,ref_control)))
        print("cost of ref control %.2f"%(self.evalControl(state,old_ref_control)))
        print("cost of no control(0) %.2f"%(self.evalControl(state,old_ref_control)))
        print("cost of const control(-1) %.2f"%(self.evalControl(state,[[-1,-1]]*self.T)))
        print("cost of const control(1) %.2f"%(self.evalControl(state,[[1,1]]*self.T)))
        '''

        #return ref_control[0]
        p.e()
        return ref_control

    def evalControl(self,state,candidate_control):
        candidate_control = np.array(candidate_control).reshape(-1,self.m)
        S = 0
        x0 = state.copy()
        x = state.copy()
        # run each simulation for self.T timesteps
        for t in range(self.T):
            control = candidate_control[t,:]
            x = self.applyDiscreteDynamics(x,control,self.dt)
            S += self.evaluateStepCost(x,control)
        S += self.evaluateTerminalCost(x,x0)
        return S

