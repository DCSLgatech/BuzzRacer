# this is one of the main files for Nick's summer work on his personal RC car
# The focus here is on control algorithms, new sensors, etc. NOT on determing the correct pathline to follow
# Therefore, the pathline will be a clearly visiable dark tape on a pale background. The line is about 0.5cm wide
# This file contains code that deals with the track setup at Nick's house, and may not be suitable for other uses

# TODO - deal with non-smooth pathlines

import numpy as np
import math
import cv2
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import pickle
import warnings
import rospy
import threading

from sensor_msgs.msg import Image
from std_msgs.msg import Float64 as float_msg
from calibration import imageutil
from cv_bridge import CvBridge, CvBridgeError

from timeUtil import execution_timer

x_size = 640
y_size = 480
crop_y_size = 240
cam = imageutil('../calibrated/')

class driveSys:

    @staticmethod
    def init():

        driveSys.bridge = CvBridge()
        rospy.init_node('driveSys_node',log_level=rospy.DEBUG, anonymous=False)

        #shutdown routine
        #rospy.on_shutdown(driveSys.cleanup)
        driveSys.throttle = 0
        driveSys.steering = 0
        driveSys.vidin = rospy.Subscriber("image_raw", Image,driveSys.callback,queue_size=1,buff_size = 2**24)
        driveSys.throttle_pub = rospy.Publisher("/throttle",float_msg, queue_size=1)
        driveSys.steering_pub = rospy.Publisher("/steer_angle",float_msg, queue_size=1)
        driveSys.test_pub = rospy.Publisher('img_test',Image, queue_size=1)
        driveSys.testimg = None
        driveSys.sizex=x_size
        driveSys.sizey=y_size
        driveSys.scaler = 25
        # unit: cm
        driveSys.lanewidth=15
        driveSys.lock = threading.Lock()

        driveSys.data = None
        while not rospy.is_shutdown():
            driveSys.lock.acquire()
            localcopy = driveSys.data
            driveSys.lock.release()

            if localcopy is not None:
                driveSys.drive(localcopy)

        rospy.spin()

        return

    # TODO handle basic cropping and color converting at this level, or better yet before it is published
    # update current version of data, thread safe
    @staticmethod
    def callback(data):
        driveSys.lock.acquire()
        driveSys.data = data
        driveSys.lock.release()
        return

    @staticmethod
    def publish():
        driveSys.throttle_pub.publish(driveSys.throttle)
        driveSys.steering_pub.publish(driveSys.steering)
        rospy.loginfo("throttle = %f steering = %f",driveSys.throttle,driveSys.steering)
        if (driveSys.testimg is not None):
            image_message = driveSys.bridge.cv2_to_imgmsg(driveSys.testimg, encoding="passthrough")
            driveSys.test_pub.publish(image_message)
        return
    
    # handles frame pre-processing and post status update
    @staticmethod
    def drive(data,noBridge = False):
        try:
            ori_frame = driveSys.bridge.imgmsg_to_cv2(data, "rgb8")
        except CvBridgeError as e:
            print(e)

        #crop
        frame = ori_frame[240:,:]
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        retval = driveSys.findCenterline(frame)
        if (retval is not None):
            throttle = 0.247
            fit = retval
            steer_angle = driveSys.purePursuit(fit)
            if (steer_angle is not None):
                steer = driveSys.calcSteer(steer_angle)
            else:
                saveImg(ori_frame)
        else:
            throttle = 0
            steer = 0


        driveSys.throttle = throttle
        driveSys.steering = steer
        driveSys.publish()
        return


    # given a steering angle, provide a -1.0-1.0 value for rostopic /steer_angle
    # XXX this is a temporary measure, this should be handled by arduino
    @staticmethod
    def calcSteer(angle):
        # values obtained from testing
        val = 0.0479*angle+0.2734
        print('steer=',val)
        if (val>1 or val<-1):
            print('insufficient steering')

        return np.clip(val,-1,1)

    # given a gray image, spit out:
    #   a centerline curve x=f(y), 2nd polynomial. with car's rear axle  as (0,0)
    @staticmethod
    def findCenterline(gray):

        ori = gray.copy()


        #gray = normalize(gray)
        alpha = 20
        gauss = cv2.GaussianBlur(gray, (0, 0), sigmaX=alpha, sigmaY=alpha)

        gray = gray - gauss
        binary = normalize(gray)>1
        binary = binary.astype(np.uint8)

        #label connected components
        connectivity = 8 
        #XXX will doing one w/o stats for fast removal quicker?
        output = cv2.connectedComponentsWithStats(binary, connectivity, cv2.CV_32S)
        # The first cell is the number of labels
        num_labels = output[0]
        # The second cell is the label matrix
        labels = output[1]
        # The third cell is the stat matrix
        stats = output[2]
        # The fourth cell is the centroid matrix
        centroids = output[3]


        # apply known rejection standards here
        goodLabels = []
        for i in range(num_labels):
            if (stats[i,cv2.CC_STAT_AREA]<1000 or stats[i,cv2.CC_STAT_TOP]+stats[i,cv2.CC_STAT_HEIGHT] < 220 or stats[i,cv2.CC_STAT_HEIGHT]<80):
                binary[labels==i]=0
            else:
                goodLabels.append(i)

        if (len(goodLabels)==0):
            print(' no good feature')
            return
        else:
            print('good feature :  '+str(len(goodLabels)))

        cv2.namedWindow('binary')
        cv2.imshow('binary',binary)
        cv2.createTrackbar('label','binary',1,len(goodLabels)-1,nothing)
        last_selected = 1

        # visualize the remaining labels
        while(1):

            selected = goodLabels[cv2.getTrackbarPos('label','binary')]

            binaryGB = binary.copy()
            binaryGB[labels==selected] = 0
            testimg = 255*np.dstack([binary,binaryGB,binaryGB])
            cv2.imshow('binary',testimg)

            #list info here

            if (selected != last_selected):
                print('label --'+str(selected))
                print('Area --\t'+str(stats[selected,cv2.CC_STAT_AREA]))
                print('Bottom --\t'+str(stats[selected,cv2.CC_STAT_TOP]+stats[selected,cv2.CC_STAT_HEIGHT]))
                print('Height --\t'+str(stats[selected,cv2.CC_STAT_HEIGHT]))
                print('WIDTH --\t'+str(stats[selected,cv2.CC_STAT_WIDTH]))
                print('---------------------------------\n\n')
                last_selected = selected

            k = cv2.waitKey(1) & 0xFF
            if k == 27:
                print('next')
                break
        cv2.destroyAllWindows()
        return



        # find the two longest left edges
        line_labels = np.argsort(stats[:,cv2.CC_STAT_AREA][1:])[-2:]+1


        # list of centroids with corresponding left/right edge (of a white line)
        long_edge_centroids = []
        long_edge_lr = ""
        long_edge_label = []

        #XXX error: out of bond
        if (stats[line_labels[0],cv2.CC_STAT_AREA]>300):
            long_edge_centroids.append(centroids[line_labels[0],0])
            long_edge_lr += 'L'
            long_edge_label.append(labels==line_labels[0])
        if (stats[line_labels[1],cv2.CC_STAT_AREA]>300):
            long_edge_centroids.append(centroids[line_labels[1],0])
            long_edge_lr += 'L'
            long_edge_label.append(labels==line_labels[1])

        t.e('find left edges')

        # find right edge of lanes
        # XXX gray>1.5 is a sketchy solution that cut data size in half
        t.s('find right edg')
        binary_output =  np.zeros_like(gray,dtype=np.uint8)
        binary_output[(gray>1.5)&(sobelx<0) & (norm>1)] = 1
        
        #label connected components
        connectivity = 8 
        output = cv2.connectedComponentsWithStats(binary_output, connectivity, cv2.CV_32S)
        # The first cell is the number of labels
        num_labels = output[0]
        # The second cell is the label matrix
        labels = output[1]
        # The third cell is the stat matrix
        stats = output[2]
        # The fourth cell is the centroid matrix
        centroids = output[3]


        line_labels = np.argsort(stats[:,cv2.CC_STAT_AREA][1:])[-2:]+1

        if ( stats[line_labels[0],cv2.CC_STAT_AREA]>300):
            long_edge_centroids.append(centroids[line_labels[0],0])
            long_edge_lr += 'R'
            long_edge_label.append(labels==line_labels[0])

        if ( stats[line_labels[1],cv2.CC_STAT_AREA]>300):

            long_edge_centroids.append(centroids[line_labels[1],0])
            long_edge_lr += 'R'
            long_edge_label.append(labels==line_labels[1])


        # rank the edges based on centroid
        order = np.argsort(long_edge_centroids)
        long_edge_centroids = np.array(long_edge_centroids)[order]
        temp_lr = ""
        for i in order:
            temp_lr += long_edge_lr[i]
        long_edge_lr = temp_lr
        long_edge_label = np.array(long_edge_label)[order]

        t.e('find right edg')
        # now we analyze the long edges we have
        # case notation: e.g.(LR) -> left edge, right edge, from left to right

        # this logical is based on the assumption that the edges we find are lane edges
        # now we distinguish between several situations
        t.s('find centerline - lr analysis')
        flag_fail_to_find = False
        flag_good_road = False
        flag_one_lane = False
        centerPoly = None

        # case 1: if we find one and only one pattern (?RL?), we got a match
        if (long_edge_lr.count('RL')==1):
            index = long_edge_lr.find('RL')
            with warnings.catch_warnings(record=True) as w:
                left_poly = fitPoly(long_edge_label[index])
                index += 1
                right_poly = fitPoly(long_edge_label[index])
                if len(w)>0:
                    raise Exception('fail to fit poly')

                else:
                    flag_good_road = True
                    center_poly = findCenterFromSide(left_poly,right_poly)
        
        # case 2: we only see one edge of any sort
        if (len(long_edge_lr)==1):
            with warnings.catch_warnings(record=True) as w:
                side_poly = fitPoly(long_edge_label[0])
                if len(w)>0:
                    raise Exception('fail to fit poly')
                else:
                    flag_one_lane = True

        # case 3: if we get  (LR), then we are stepping on a lane, but don't know which that lane is (LR)
        # in this case drive on this lane until we see the other lane 
        elif (long_edge_lr == 'LR'):
            index = 0
            with warnings.catch_warnings(record=True) as w:
                left_poly = fitPoly(long_edge_label[index])
                index += 1
                right_poly = fitPoly(long_edge_label[index])
                if len(w)>0:
                    raise Exception('fail to fit poly')

                else:
                    flag_one_lane = True
                    side_poly = findCenterFromSide(left_poly,right_poly)

        # otherwise we are completely lost
        else:
            flag_fail_to_find = True
            pass

        # based on whether the line inclines to the left or right, guess which side it is
        if (flag_one_lane == True):
            x0 = side_poly[0]*1**2 + side_poly[1]*1 + side_poly[2] - x_size/2
            x1 = side_poly[0]*crop_y_size**2 + side_poly[1]*crop_y_size + side_poly[2] - x_size/2
            if (x1-x0>0):
                side = 'right'
            else:
                side = 'left'
        t.e('find centerline - lr analysis')

        
        binary_output=None
        if (flag_good_road == True):
            # DEBUG - for producing anice testimg
            '''
            t.s('generate testimg')
            # Generate x and y values for plotting
            ploty = np.linspace(0, gray.shape[0]-1, gray.shape[0] )
            left_fitx = left_poly[0]*ploty**2 + left_poly[1]*ploty + left_poly[2]
            right_fitx = right_poly[0]*ploty**2 + right_poly[1]*ploty + right_poly[2] 
            # Recast the x and y points into usable format for cv2.fillPoly()
            pts_left = np.array([np.transpose(np.vstack([left_fitx, ploty]))])
            pts_right = np.array([np.flipud(np.transpose(np.vstack([right_fitx, ploty])))])
            pts = np.hstack((pts_left, pts_right))

            # Draw the lane onto the blank image
            binary_output =  np.zeros_like(gray,dtype=np.uint8)
            cv2.fillPoly(binary_output, np.int_([pts]), 1)

            # Draw centerline onto the image
            centerlinex = center_poly[0]*ploty**2 + center_poly[1]*ploty + center_poly[2]
            pts_center = np.array(np.transpose(np.vstack([centerlinex, ploty])))
            cv2.polylines(binary_output,np.int_([pts_center]), False, 5,10)

            #driveSys.testimg = np.dstack(40*[binary_output,binary_output,binary_output])
            # END-DEBUG
            t.e('generate testimg')
            '''
            pass

            # get centerline in top-down view

	    t.s('change centerline perspective')

            # prepare sample points
            ploty = np.linspace(0, gray.shape[0]-1, gray.shape[0] )
            centerlinex = center_poly[0]*ploty**2 + center_poly[1]*ploty + center_poly[2]

            # convert back to uncropped space
            ploty += y_size/2
            pts_center = np.array(np.transpose(np.vstack([centerlinex, ploty])))
            pts_center = cam.undistortPts(np.reshape(pts_center,(1,-1,2)))

            # unwarp and change of units
            for i in range(len(pts_center[0])):
                pts_center[0,i,0],pts_center[0,i,1] = transform(pts_center[0,i,0],pts_center[0,i,1])
                
            # now pts_center should contain points in vehicle coordinate with x axis being rear axle,unit in cm
            #fit(y,x)
            fit = np.polyfit(pts_center[0,:,1],pts_center[0,:,0],2)
	    t.e('change centerline perspective')


            return fit


        if (flag_one_lane == True):

            # DEBUG - for producing anice testimg

            '''
	    t.s('generate testimg')
            # Generate x and y values for plotting
            ploty = np.linspace(0, gray.shape[0]-1, gray.shape[0] )

            binary_output =  np.zeros_like(gray,dtype=np.uint8)

            # Draw centerline onto the image
            sidelinex = side_poly[0]*ploty**2 + side_poly[1]*ploty + side_poly[2]
            pts_side = np.array(np.transpose(np.vstack([sidelinex, ploty])))
            cv2.polylines(binary_output,np.int_([pts_side]), False, 1,1)

            #driveSys.testimg = np.dstack(250*[binary_output,binary_output,binary_output])
	    t.e('generate testimg')
            '''
            # END-DEBUG

            # get centerline in top-down view

	    t.s('change centerline perspective')

            # prepare sample points
            ploty = np.linspace(0, gray.shape[0]-1, gray.shape[0] )
            sidelinex = side_poly[0]*ploty**2 + side_poly[1]*ploty + side_poly[2]

            # convert back to uncropped space
            ploty += y_size/2
            pts_side = np.array(np.transpose(np.vstack([sidelinex, ploty])))
            pts_side = cam.undistortPts(np.reshape(pts_side,(1,-1,2)))

            # unwarp and change of units
            for i in range(len(pts_side[0])):
                pts_side[0,i,0],pts_side[0,i,1] = transform(pts_side[0,i,0],pts_side[0,i,1])
                
                # now pts_side should contain points in vehicle coordinate with x axis being rear axle,unit in cm
                #XXX this is really stupid and inefficient
                if (side == 'left'):
                    pts_side[0,i,0] = pts_side[0,i,0]+0.5*driveSys.lanewidth
                else:
                    pts_side[0,i,0] = pts_side[0,i,0]-0.5*driveSys.lanewidth

            # now pts_side should contain points in vehicle coordinate with x axis being rear axle,unit in cm
            #fit(y,x)
            fit = np.polyfit(pts_side[0,:,1],pts_side[0,:,0],2)

	    t.e('change centerline perspective')


            return fit

        return None

    @staticmethod
    def purePursuit(fit,lookahead=27):
        pic = debugimg(fit)
        # anchor point coincide with rear axle
        # calculate target point
        a = fit[0]
        b = fit[1]
        c = fit[2]
        p = []
        p.append(a**2)
        p.append(2*a*b)
        p.append(b**2+2*a*c+1)
        p.append(2*b*c)
        p.append(c**2-lookahead**2)
        p = np.array(p)
        roots = np.roots(p)
        roots = roots[np.abs(roots.imag)<0.00001]
        roots = roots.real
        roots = roots[(roots<lookahead) & (roots>0)]
        if ((roots is None) or (len(roots)==0)):
            return None
        roots.sort()
        y = roots[-1]
        x = fit[0]*(y**2) + fit[1]*y + fit[2]

        # find curvature to that point
        curvature = (2*x)/(lookahead**2)

        # find steering angle for this curvature
        # not sure about this XXX
        wheelbase = 11
        steer_angle = math.atan(wheelbase*curvature)/math.pi*180
        return steer_angle
            


# universal functions

# save frame as an image for debug
def saveImg(frame, steering=0, throttle=0):
    #text = "Steering: %f, Throttle: %f" % (steering, throttle)
    #cv2.putText(frame, text, (20, 20), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255),2)
    image_message = driveSys.bridge.cv2_to_imgmsg(frame, encoding="bgr8")
    nameTime = str(round(time.time()))
    name = './pics/' + nameTime + ".png"
    cv2.imwrite(name, frame)
    rospy.loginfo("debug img %s saved", nameTime+'.png')
    return



# generate a top-down view for transformed fitted curve
def debugimg(poly):
    # Generate x and y values for plotting
    ploty = np.linspace(0,40,41)

    binary_output =  np.zeros([41,20],dtype=np.uint8)

    # Draw centerline onto the image
    x = poly[0]*ploty**2 + poly[1]*ploty + poly[2]
    x = x+10
    ploty = 40-ploty
    pts = np.array(np.transpose(np.vstack([x, ploty])))
    cv2.polylines(binary_output,np.int_([pts]), False, 1,1)

    return  binary_output

def showg(img):
    plt.imshow(img,cmap='gray',interpolation='nearest')
    plt.show()
    return

def show(img):
    plt.imshow(img,interpolation='nearest')
    plt.show()
    return

def showmg(img1,img2=None,img3=None,img4=None):
    plt.subplot(221)
    plt.imshow(img1,cmap='gray',interpolation='nearest')
    if (img2 is not None):
        plt.subplot(222)
        plt.imshow(img2,cmap='gray',interpolation='nearest')
    if (img3 is not None):
        plt.subplot(223)
        plt.imshow(img3,cmap='gray',interpolation='nearest')
    if (img4 is not None):
        plt.subplot(224)
        plt.imshow(img4,cmap='gray',interpolation='nearest')

    plt.show()
    return

# matrix obtained from matlab linear fit, mse=1.79 on 17 data points
def transform(x,y):
    return 0.035*x-11.5713, -0.1111*y+74.1771

# XXX this is not accurate
def obs_transform(x, y):
    # alpha = 20 degrees, verticalFOV(vFov) = 15 degrees, horizontalFOV(hFov) = 15 degrees, h = 5.4 cm
    alpha = 3
    vFov = 27.0
    hFov = 40.0
    h = 5.4

    ob = h / math.cos(math.radians(90 - alpha - vFov))
    op = math.cos(math.radians(vFov)) * ob
    bp = math.sin(math.radians(vFov)) * ob

    if y > 0 and y <= 240:
        angle = math.degrees(math.atan((240-y)/240.0*bp/op)) + 90.0 - alpha
        actualY = math.tan(math.radians(angle))*h
    else:
        angle = 90 - alpha - math.degrees(math.atan((y-240)/240*bp/op))
        actualY = math.tan(math.radians(angle))*h

    om = actualY * math.tan(math.radians(hFov))
    
    if x > 0 and x <= 320:
        actualX = -(320-x)/320.0*om
    else:
        actualX = (x-320)/320.0*om
        
    actualY = actualY + 14
    
    return actualX, actualY
# normalize an image with (0,255)
def normalize(data):
    data = data.astype(np.float32)
    data = data/255
    mean = np.mean(data)
    stddev = np.std(data)
    data = (data-mean)/stddev
    return data

# do a local normalization on grayscale image with [0,1] space
# alpha and beta are the sigma values for the two blur
def localNormalize(float_gray, alpha=2, beta=20):

    blur = cv2.GaussianBlur(float_gray, (0, 0), sigmaX=alpha, sigmaY=alpha)
    num = float_gray - blur

    blur = cv2.GaussianBlur(num*num, (0, 0), sigmaX=beta, sigmaY=beta)
    den = cv2.pow(blur, 0.5)

    gray = num / den

    cv2.normalize(gray, dst=gray, alpha=0.0, beta=1.0, norm_type=cv2.NORM_MINMAX)
    return gray

def warp(image):

    warped = cv2.warpPerspective(image, M, (image.shape[1],image.shape[0]), flags=cv2.INTER_LINEAR)
    return warped


# given a binary image BINARY, where 1 means data and 0 means nothing
# return the best fit polynomial
def fitPoly(binary):
    nonzero = binary.nonzero()
    nonzeroy = np.array(nonzero[0])
    nonzerox = np.array(nonzero[1])
    x = nonzerox
    y = nonzeroy

    fit = np.polyfit(y, x, 2)
    return fit


# find the centerline of two polynomials
def findCenterFromSide(left,right):
    return (left+right)/2

    
# run the pipeline on a test img    
def testimg(filename):
    image = cv2.imread(filename)
    if (image is None):
        print('No such file'+filename)
        return

    # we hold undistortion after lane finding because this operation discards data
    #image = cam.undistort(image)
    image = image.astype(np.float32)
    image = image[:,:,0]-image[:,:,2]+image[:,:,1]-image[:,:,2]

    #crop
    image = image[240:,:]
    driveSys.lanewidth=15
    driveSys.scaler = 25

    t.s()
    fit = driveSys.findCenterline(image)
    return
    steer_angle = driveSys.purePursuit(fit)
    steer = driveSys.calcSteer(steer_angle)
    t.e()
    return
def nothing(x):
    pass


# test perspective changing algorithm against measured value
def testperspective():
    src = np.array([[207,370], [220,387],[238,411],[430,368],[461,376],[486,379],[497,386],[554,385],[580,384],[612,384],[432,423],[330,333],[394,411],[390,398],[369,338],[600,394],[613,405]])
    dest = np.array([[-5,33],  [-4,31],  [-3,29],[4,33],[5,32],[6,32],[6,31],[8,31],[9,31],[10,31],[3,28],[0,38],[2,29],[2,30],[2,37],[9,30],[9,29]])
    mse = np.array([0,0],dtype=np.float64)
    for (a,b) in zip(src,dest):
        guess = transform(a[0],a[1])
        diff = guess-b
        mse += diff**2

    print(mse**0.5)
    return

    

t = execution_timer(False)
if __name__ == '__main__':

    print('begin')
    #testpics =['../perspectiveCali/mid.png','../perspectiveCali/left.png','../img/0.png','../img/1.png','../img/2.png','../img/3.png','../img/4.png','../img/5.png','../img/6.png','../img/7.png'] 
    testpics =[ '../img/pic1.jpeg',
                '../img/pic2.jpeg',
                '../img/pic3.jpeg',
                '../img/pic4.jpeg',
                '../img/pic5.jpeg',
                '../img/pic6.jpeg',
                '../img/pic7.jpeg',
                '../img/pic8.jpeg',
                '../img/pic9.jpeg',
                '../img/pic10.jpeg',
                '../img/pic11.jpeg',
                '../img/pic12.jpeg',
                '../img/pic13.jpeg',
                '../img/pic14.jpeg',
                '../img/pic15.jpeg',
                '../img/pic16.jpeg',
                '../img/pic17.jpeg',
                '../img/pic18.jpeg',
                '../img/pic19.jpeg',
                '../img/pic20.jpeg',
                '../img/pic21.jpeg',
                '../img/pic22.jpeg',
                '../img/pic23.jpeg',
                '../img/pic24.jpeg',
                '../img/pic25.jpeg',
                '../img/pic26.jpeg',
                '../img/pic27.jpeg']
    
    #driveSys.init()
    for i in range(27):
        testimg(testpics[i])
    #t.summary()
