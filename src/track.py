#this file contains all data structure and algorithm to :
# describe an RCP track
# describe a raceline within the track
# provide desired trajectory(raceline) given a car's location within thte track

import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import splprep, splev
import cv2


class Node:
    def __init__(self,previous=None,entrydir=None):
        # entry direction
        self.entry = entrydir
        # previous node
        self.previous = previous
        # exit direction
        self.exit = None
        self.next = None
        return
    def setExit(self,exit=None):
        self.exit = exit
        return
    def setEntry(self,entry=None):
        self.entry = entry
        return

class RCPtrack:
    def __init__(self):
        self.resolution = 100

    def initTrack(self,description, gridsize, scale,savepath=None):
        # build a track and save it
        # description: direction to go to reach next grid u(p), r(ight),d(own), l(eft)
        # e.g For a track like this                    
        #         /-\            
        #         | |            
        #         \_/            
        # The trajectory description, starting from the bottom left corner (origin) would be
        # uurrddll (cw)(string), it does not matter which direction is usd

        # gridsize (rows, cols), size of thr track
        # savepath, where to store the track file

        # scale : meters per grid width (for RCP roughly 0.565m)
        self.scale = scale
        self.gridsize = gridsize
        self.track_length = len(description)
        
        grid = [[None for i in range(gridsize[0])] for j in range(gridsize[1])]

        current_index = np.array([0,0])
        grid[0][0] = Node()
        current_node = grid[0][0]
        lookup_table_alt = {'u':(0,1),'d':(0,-1),'r':(1,0),'l':(-1,0) }

        for i in range(len(description)):
            current_node.setExit(description[i])

            previous_node = current_node
            if description[i] in lookup_table_alt:
                current_index += lookup_table_alt[description[i]]
            else:
                print("error, unexpected value in description")
                exit(1)
            if all(current_index == [0,0]):
                grid[0][0].setEntry(description[i])
                # if not met, description does not lead back to origin
                assert i==len(description)-1
                break

            # assert description does not go beyond defined grid
            assert (current_index[0]<gridsize[1]) & (current_index[1]<gridsize[0])

            current_node = Node(previous=previous_node, entrydir=description[i])
            grid[current_index[0]][current_index[1]] = current_node

        #grid[0][0].setEntry(description[-1])


        # process the linked list, replace with the following
        # straight segment = WE(EW), NS(SN)
        # curved segment = SE,SW,NE,NW
        lookup_table = { 'WE':['rr','ll'],'NS':['uu','dd'],'SE':['ur','ld'],'SW':['ul','rd'],'NE':['dr','lu'],'NW':['ru','dl']}
        for i in range(gridsize[1]):
            for j in range(gridsize[0]):
                node = grid[i][j]
                if node == None:
                    continue

                signature = node.entry+node.exit
                for entry in lookup_table:
                    if signature in lookup_table[entry]:
                        grid[i][j] = entry

                if grid[i][j] is Node:
                    print('bad track description: '+signature)
                    exit(1)

        self.track = grid
        # TODO add save pickle function
        return 


    def drawTrack(self, img=None,show=True):
        # show a picture of the track
        # resolution : pixels per grid length
        color_side = (250,0,0)
        # boundary width / grid width
        deadzone = 0.09
        gs = self.resolution

        # prepare straight section (WE)
        straight = 255*np.ones([gs,gs,3],dtype='uint8')
        straight = cv2.rectangle(straight, (0,0),(gs-1,int(deadzone*gs)),color_side,-1)
        straight = cv2.rectangle(straight, (0,int((1-deadzone)*gs)),(gs-1,gs-1),color_side,-1)
        WE = straight

        # prepare straight section (SE)
        turn = 255*np.ones([gs,gs,3],dtype='uint8')
        turn = cv2.rectangle(turn, (0,0),(int(deadzone*gs),gs-1),color_side,-1)
        turn = cv2.rectangle(turn, (0,0),(gs-1,int(deadzone*gs)),color_side,-1)
        turn = cv2.rectangle(turn, (0,0), (int(0.5*gs),int(0.5*gs)),color_side,-1)
        turn = cv2.circle(turn, (int(0.5*gs),int(0.5*gs)),int((0.5-deadzone)*gs),(255,255,255),-1)
        turn = cv2.circle(turn, (gs-1,gs-1),int(deadzone*gs),color_side,-1)
        SE = turn

        # prepare canvas
        rows = self.gridsize[0]
        cols = self.gridsize[1]
        if img is None:
            img = 255*np.ones([gs*rows,gs*cols,3],dtype='uint8')
        lookup_table = {'SE':0,'SW':270,'NE':90,'NW':180}
        for i in range(cols):
            for j in range(rows):
                signature = self.track[i][rows-1-j]
                if signature == None:
                    continue

                if (signature == 'WE'):
                    img[j*gs:(j+1)*gs,i*gs:(i+1)*gs] = WE
                    continue
                elif (signature == 'NS'):
                    M = cv2.getRotationMatrix2D((gs/2,gs/2),90,1.01)
                    NS = cv2.warpAffine(WE,M,(gs,gs))
                    img[j*gs:(j+1)*gs,i*gs:(i+1)*gs] = NS
                    continue
                elif (signature in lookup_table):
                    M = cv2.getRotationMatrix2D((gs/2,gs/2),lookup_table[signature],1.01)
                    dst = cv2.warpAffine(SE,M,(gs,gs))
                    img[j*gs:(j+1)*gs,i*gs:(i+1)*gs] = dst
                    continue
                else:
                    print("err, unexpected track designation : " + signature)

        # some rotation are not perfect and leave a black gap
        img = cv2.medianBlur(img,5)
        if show:
            plt.imshow(img)
            plt.show()

        return img
    
    def loadTrackfromFile(self,filename,newtrack,gridsize):
        # load a track 
        self.track = newtrack
        self.gridsize = gridsize

        return

    def initRaceline(self,start, start_direction, filename=None):
        #init a raceline from current track, save if specified 
        # start: which grid to start from, e.g. (3,3)
        # start_direction: which direction to go. 
        #note use the direction for ENTERING that grid element 
        # e.g. 'l' or 'd' for a NE oriented turn
        self.ctrl_pts = []
        lookup_table = { 'WE':['rr','ll'],'NS':['uu','dd'],'SE':['ur','ld'],'SW':['ul','rd'],'NE':['dr','lu'],'NW':['ru','dl']}
        lookup_table_alt = {'u':(0,1),'d':(0,-1),'r':(1,0),'l':(-1,0) }
        center = lambda x,y : [(x+0.5)*self.scale,(y+0.5)*self.scale]

        left = lambda x,y : [(x)*self.scale,(y+0.5)*self.scale]
        right = lambda x,y : [(x+1)*self.scale,(y+0.5)*self.scale]
        up = lambda x,y : [(x+0.5)*self.scale,(y+1)*self.scale]
        down = lambda x,y : [(x+0.5)*self.scale,(y)*self.scale]

        # direction of entry
        entry = start_direction
        current_coord = np.array(start,dtype='uint8')

        while (1):
            self.ctrl_pts.append(center(current_coord[0],current_coord[1])) 
            for record in lookup_table[self.track[current_coord[0]][current_coord[1]]]:
                if record[0] == entry:
                    exit = record[1]
                    break
            exit_ctrl_pt = np.array(lookup_table_alt[exit],dtype='float')/2
            exit_ctrl_pt += current_coord
            exit_ctrl_pt += np.array([0.5,0.5])
            exit_ctrl_pt *= self.scale

            self.ctrl_pts.append(list(exit_ctrl_pt))
            current_coord = current_coord + lookup_table_alt[exit]
            entry = exit

            if (all(start==current_coord)):
                break
        print(self.ctrl_pts)

        pts=np.array(self.ctrl_pts)
        tck, u = splprep(pts.T, u=np.linspace(0,self.track_length*2-1,self.track_length*2), s=0.0, per=1) 

        self.raceline = tck

        return

    def drawRaceline(self,lineColor=(0,0,255), img=None, show=True):

        rows = self.gridsize[0]
        cols = self.gridsize[1]
        res = self.resolution

        u_new = np.linspace(0,self.track_length*2-1,1000)
        x_new, y_new = splev(u_new, self.raceline, der=0)
        # convert to visualization coordinate
        x_new /= self.scale
        x_new *= self.resolution
        y_new /= self.scale
        y_new *= self.resolution
        y_new = self.resolution*rows - y_new

        if img is None:
            img = np.zeros([res*rows,res*cols,3],dtype='uint8')

        pts = np.vstack([x_new,y_new]).T
        pts = pts.reshape((-1,1,2))
        pts = pts.astype(np.int)
        img = cv2.polylines(img, [pts], isClosed=True, color=lineColor, thickness=3) 

        if show:
            plt.imshow(img)
            plt.show()

        return img

    def loadRaceline(self,filename=None):
        pass

    def saveRaceline(self,filename):
        pass

    def optimizeRaceline(self):
        pass
    def setResolution(self,res):
        self.resolution = res
        return


def show(img):
    plt.imshow(img)
    plt.show()
    return
    
if __name__ == "__main__":
    s = RCPtrack()
    # simple track
    #s.initTrack('uurrddll',(3,3),scale=1.0)
    #s.initRaceline((0,0),'l')

    # MK111 track
    s.initTrack('uuurrullurrrdddddluulddl',(6,4), scale=1.0)
    s.initRaceline((0,0),'l')
    img_track = s.drawTrack()
    img_raceline = s.drawRaceline(img=img_track)

    