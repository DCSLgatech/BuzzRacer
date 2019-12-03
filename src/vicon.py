#!/usr/bin/env python
# retrieve vicon feed from matlab and republish as ROS topic
import socket
from time import time
from struct import unpack
from math import degrees,radians

class Vicon:
    def __init__(self,IP=None,PORT=None):
        if IP is None:
            IP = "0.0.0.0"
        if PORT is None:
            PORT = 51001
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((IP, PORT))
        
    def __del__(self):
        self.sock.close()

    def getViconUpdate(self):
        data, addr = self.sock.recvfrom(256)
        frameNumber = unpack('i',data[0:4])
        #print(frameNumber)
        itemsInBlock = data[4]
        itemID = data[5]
        itemDataSize = unpack('h',data[6:8])
        itemName = data[8:32].decode("ascii")
        # raw data in mm, convert to m
        x = unpack('d',data[32:40])[0]/1000
        y = unpack('d',data[40:48])[0]/1000
        z = unpack('d',data[48:56])[0]/1000
        # euler angles,rad, rotation order: rx,ry,rz, using intermediate frame
        rx = unpack('d',data[56:64])[0]
        ry = unpack('d',data[64:72])[0]
        rz = unpack('d',data[72:80])[0]
        #print(x,y,z,degrees(rx),degrees(ry),degrees(rz))
        return (x,y,z,rx,ry,rz)

    def dummyUpdate(self):
        data, addr = self.sock.recvfrom(512)
        frameNumber = unpack('i',data[0:4])[0]
        #print(frameNumber)
        itemsInBlock = data[4]
        itemID = data[5]
        itemDataSize = unpack('h',data[6:8])
        itemName = data[8:32].decode("ascii")
        # raw data in mm, convert to m
        x = unpack('d',data[32:40])[0]/1000
        y = unpack('d',data[40:48])[0]/1000
        z = unpack('d',data[48:56])[0]/1000
        # euler angles,rad, rotation order: rx,ry,rz, using intermediate frame
        rx = unpack('d',data[56:64])[0]
        ry = unpack('d',data[64:72])[0]
        rz = unpack('d',data[72:80])[0]
        #print(x,y,z,degrees(rx),degrees(ry),degrees(rz))
        return frameNumber

    # do not use
    def fromFile(self,filename):
        newFile = open(filename, "wb")
        newFile.write(data)


if __name__ == '__main__':
    #f = open('samplevicon.bin','br')
    #data = f.read()
    vi = Vicon()
    tik = time()
    last_frame = None
    loss_count = 0
    while True:
        print(vi.getViconUpdate())

        
    

