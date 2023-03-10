import gymnasium as gym
import os
import sys

rl_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(1,rl_dir)

from gymnasium import spaces
import numpy as np
from math import radians,degrees
from RL.copg.rcvip_simulator.VehicleModel import VehicleModel
from RL.copg.rcvip_racing.rcvip_env_function import getRewardSingleAgent
import torch
from xml.dom.minidom import parseString

from track import TrackFactory

import pygame
#from pygame.locals import *

def fmap(val,a,b,c,d):
    retval = (val-a)/(b-a)*(d-c)+c
    retval = min(d,max(retval,c))
    return retval

class BuzzRacerEnv(gym.Env):
    metadata = {'render_modes':['human','rgb_array'],'render_fps':30}

    def __init__(self, render_mode=None):
        # s(progress), d(lateral), heading, v_x, v_y, omega
        self.observation_space = spaces.Box(low=np.array([0.0,-0.3,-radians(180),-0.05,-2.0,-np.pi*2]),high=np.array([11.5,0.3,radians(180),5.0,2.0,np.pi*2]), dtype=np.float32)
        # throttle, steering
        self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(2,), dtype=np.float32)
        self.observation_space.n = 6
        self.action_space.n = 2
        self.action = (0,0)


        assert render_mode is None or render_mode in self.metadata['render_modes']
        self.render_mode = render_mode

        self.window = None
        self.clock = None

        n_batch = 1
        self.device = torch.device('cpu') # cpu is faster
        self.vehicle_model = VehicleModel(n_batch, self.device, track='rcp')

        if self.render_mode == 'human':
            self.initVisualization()
        elif self.render_mode == 'rgb_array':
            self.initVisualization()

    # draw control related static images
    def drawControl(self,canvas, coord=(0,0)):

        # Static component
        font = pygame.font.SysFont(None,25,bold=False)
        x1 = coord[0] + 65
        y1 = coord[1] + 12
        w = 100
        h = 20
        pygame.draw.rect(canvas,(0,0,0), (x1, y1, w,h),width=2)
        text = font.render('Steering',False,(0,0,0))
        canvas.blit(text,(0,y1))

        x2 = x1
        y2 = y1 + 30
        pygame.draw.rect(canvas,(0,0,0), (x2, y2, w,h),width=2)
        text = font.render('throttle',False,(0,0,0))
        canvas.blit(text,(0,y2))

        # active component
        # throttle, control
        print(self.action)
        throttle,steering = self.action
        if (steering > 0):
            length = fmap(steering,0,radians(26.7),0,w/2)
            pygame.draw.rect(canvas,(0,200,0), (x1+w/2, y1, length,h),width=0)
            print(length)
        else:
            length = fmap(-steering,0,radians(26.7),0,w/2)
            pygame.draw.rect(canvas,(0,200,0), (x1+w/2-length, y1, length,h),width=0)
            print(length)

        if (throttle > 0):
            length = fmap(throttle,0,1,0,w/2)
            pygame.draw.rect(canvas,(0,200,0), (x2+w/2, y2, length,h),width=0)
            print(length)
        else:
            length = fmap(-throttle,0,1,0,w/2)
            pygame.draw.rect(canvas,(0,200,0), (x2+w/2-length, y2, length,h),width=0)
            print(length)

        return

        return 
        #x1 and y1 are the origin values -- need to be changed if origin changes
        x1 = coord[0] + 30
        y1 = coord[1]
        # Add steering bar
        img = cv2.rectangle(img, (x1 + 4, y1 + 25), (x1 + 100, y1 + 40), (0, 0, 255), 1)
        img = cv2.putText(img, 'Steering', (x1 + 104, y1 + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
        #end_coordinate = int(50 - (steering * 100))              
        #img = cv2.rectangle(img, (x1 + 50, y1 + 25), (x1 + end_coordinate, y1 + 40), (0, 255, 0), -1)
        
        # Add Throttle bar
        img = cv2.rectangle(img, (x1 + 4, y1 + 45), (x1 + 100, y1 + 60), (0,0,255), 1)
        img = cv2.putText(img, 'Throttle', (x1 + 104, y1 + 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
        img = self.overlayCarRenderingRaw(img,car, (x2,y2))
        #throttle_end = int(50+(72*throttle))
        #img = cv2.rectangle(img, (x1 + 52, y1 + 45), (x1 + throttle_end, y1 + 60), (0, 255, 0), -1)

        # car
        x2 = coord[0] + 20
        y2 = coord[1] + 50
        img = self.overlayCarRenderingRaw(img,car, (x2,y2))
        
        return img

    def initVisualization(self):
        pygame.init()
        pygame.font.init()

        pygame.display.set_caption('BuzzRacer')
        pygame.mouse.set_visible(False)

        self.clock = pygame.time.Clock()

        # generate track background
    
        config = parseString('<track>full</track>')
        config_track= config.getElementsByTagName('track')[0]
        self.track = TrackFactory(self,config_track)
        self.img_track = self.track.drawTrack()
        self.img_blank_track = self.img_track.copy()
        self.img_track_raceline = self.track.drawRaceline(img=self.img_track)
        self.background = pygame.surfarray.make_surface(self.img_track_raceline[:,:,::-1])
        self.background = pygame.transform.flip(self.background, False, True)
        self.background = pygame.transform.rotate(self.background, -90)

        # (480,720)
        self.screen = pygame.display.set_mode(self.background.get_size(), pygame.SCALED)
        self.background = self.background.convert()

        self.car_image = self.load_image('data/porsche_orange.png')
        # TODO figure out correct dimension
        height = self.car_image.get_size()[1]
        car_width = 0.0461
        scale = 40.0/height/200.0*self.track.resolution/0.0461*car_width

        ori_size = self.car_image.get_size()
        self.car_image = pygame.transform.scale(self.car_image,(scale*ori_size[0],scale*ori_size[1]))

        '''
        # text example
        if pygame.font:
            font = pygame.font.Font(None,64)
            text = font.render('render text', True, (10,10,10))
            textpos = text.get_rect(centerx=background.get_width()/2,y=10)
            background.blit(text,textpos)
        '''

    def load_image(self, filename, colorkey=None, scale=1):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        fullname = os.path.join(base_dir, filename)

        image = pygame.image.load(fullname)
        image = image.convert_alpha()

        size = image.get_size()
        size = (size[0] * scale, size[1] * scale)
        image = pygame.transform.scale(image, size)

        if colorkey is not None:
            if colorkey == -1:
                colorkey = image.get_at((0, 0))
            image.set_colorkey(colorkey, pygame.RLEACCEL)
        return image

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        states = self.generateRandomStates()
        self.torch_states = torch.tensor([states],dtype=torch.float32)
        bounds = self.vehicle_model.getLocalBounds(self.torch_states[:,0])
        reward, done = getRewardSingleAgent(self.torch_states, bounds ,self.torch_states,  self.device)
        while (done):
            states = self.generateRandomStates()
            self.torch_states = torch.tensor([states],dtype=torch.float32)
            reward, done = getRewardSingleAgent(self.torch_states, bounds ,self.torch_states,  self.device)

        observation = states
        info = None
        if self.render_mode == 'human':
            self._render_frame()
        return observation,info

    def generateRandomStates(self):
        random = self.np_random
        s = random.uniform(0,11.4)
        d = random.uniform(-0.2,0.2)
        heading = random.uniform(-radians(20),radians(20))
        v_x = random.uniform(0.3,2.0)
        v_y = random.uniform(-0.5,0.5)
        omega = random.uniform(-radians(5),radians(5))

        states = (s,d,heading,v_x,v_y,omega)
        return states

    def step(self, action):
        torch_action = torch.tensor(action,dtype=torch.float32).reshape(-1,2)
        last_torch_states = self.torch_states
        self.torch_states = self.vehicle_model.dynModelBlendBatch(self.torch_states, torch_action)
        bounds = self.vehicle_model.getLocalBounds(self.torch_states[:,0])
        reward, done = getRewardSingleAgent(self.torch_states, bounds ,last_torch_states,  self.device)

        if self.render_mode == 'human':
            self._render_frame()
        observation = tuple(self.torch_states.flatten().numpy())
        reward = reward.item()
        terminated = done.item()
        truncated = False
        info = None
        self.action = tuple(action)
        return observation, reward, terminated, truncated, info


    def render(self):
        if self.render_mode == "rgb_array":
            return self._render_frame()

    def _render_frame(self):
        # find car position
        local_state = self.torch_states.numpy()
        global_state = self.vehicle_model.fromLocalToGlobal(local_state).flatten()
        x,y,heading,v_forward,v_sideway,omega = global_state

        car_image = pygame.transform.rotate(self.car_image, degrees(heading))
        car_rect = self.car_image.get_rect()
        car_rect.center = self.track.m2canvas((x,y))

        self.screen.blit(self.background, (0,0))
        self.screen.blit(car_image,car_rect)
        self.drawControl(self.screen)

        if (self.render_mode == 'human'):
            pygame.display.flip()
            # We need to ensure that human-rendering occurs at the predefined framerate.
            # The following line will automatically add a delay to keep the framerate stable.
            self.clock.tick(self.metadata["render_fps"])
        elif (self.render_mode == 'rgb_array'):
            return np.transpose( np.array(pygame.surfarray.pixels3d(self.screen)),axes=(1,0,2) )
            

    def close(self):
        if self.window is not None:
            pygame.display.quit()
            pygame.quit()
