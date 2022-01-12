import sys
from common import *
import pickle
import matplotlib.pyplot as plt
from TrackFactory import TrackFactory
import cv2

def plotTraj(track, filename, img, color, text):
    global offset
    with open(filename, 'rb') as f:
        data = pickle.load(f)
    data = np.array(data).squeeze(1)

    x = data[:,1]
    y = data[:,2]
    points = np.vstack([x,y]).T
    track.drawPolyline(points, img, lineColor=color,thickness=2)
    return img

    # font
    font = cv2.FONT_HERSHEY_SIMPLEX
    # org
    org = (20, 50+offset)
    # fontScale
    fontScale = 1
    # Line thickness of 2 px
    thickness = 2
    # Using cv2.putText() method
    img = cv2.putText(img, text, org, font,
                       fontScale, color, thickness, cv2.LINE_AA)
    offset += 30

    return img


# load blank canvas
with open("track_img.p", 'rb') as f:
    img = pickle.load(f)

img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
fig = plt.figure()
plt.imshow(img)
plt.show()


track = TrackFactory(name='full')

ccmppi_logno = 2652
mppi_injected_logno = 2651
indexes = range(2740,2770,2)

for index in indexes:
    filename = "../log/kinematics_results/full_state"+str(index)+".p"
    img1 = plotTraj(track,filename, img.copy(), (0,0,255), "sample")

    img1 = np.array(img1,dtype=np.uint8)

    img1 = cv2.cvtColor(img1, cv2.COLOR_BGR2RGB)

    fig = plt.figure()
    print(index)
    plt.imshow(img1)
    #fig.savefig('out.png', bbox_inches='tight',transparent=True, pad_inches=0)
    plt.show()
