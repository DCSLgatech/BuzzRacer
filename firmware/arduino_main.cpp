// Arduino firmware for RC-VIP
// WARNING: NEVER push high to both MOSFETs on one side, this will create a short
// and burn out the MOSFETs instantly.

//
//  Updates:
// // June 2018: merged throttle and steering topic
// // June 2018: added IMU support
// // June 2018: added battery voltage sensor(30k/7.5k resistor voltage divider)
//
//
//
// // MPU6050 code from Jeff Rowberg <jeff@rowberg.net>
// // Updates should (hopefully) always be available at https://github.com/jrowberg/i2cdevlib
// //
// //
// //
// /* ============================================
// I2Cdev device library code is placed under the MIT license
// Copyright (c) 2012 Jeff Rowberg
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.
// ===============================================
// */
//
#include <Arduino.h>
#include <ros.h>
#include <std_msgs/Float64.h>
#include <rc_vip/CarSensors.h>
#include <rc_vip/CarControl.h>
#include <Servo.h>

// I2Cdev and MPU6050 must be installed as libraries, or else the .cpp/.h files
// for both classes must be in the include path of your project
#include "I2Cdev.h"
#include "MPU6050.h"

// Arduino Wire library is required if I2Cdev I2CDEV_ARDUINO_WIRE implementation
// is used in I2Cdev.h
#if I2CDEV_IMPLEMENTATION == I2CDEV_ARDUINO_WIRE
    #include "Wire.h"
#endif

#define LED_PIN 13
#define VOLTAGEDIVIDER_PIN A3


// ---------- H-bridge Control ------------
// Timer interrupt based PWM control for H bridge
// Current off-time method: tie both end to GND
// Also RN the car only goes in one direction


// All pins are high enable
#define PORT_POS_UP 9    
#define PORT_POS_DOWN 6 
#define PORT_NEG_UP 11
#define PORT_NEG_DOWN 10

// Timers usage
//timer0 -> Arduino millis() and delay()
//timer1 -> Servo lib
//timer2 -> synchronized multi-channel PWM
// if additional ISP are needed, 2B compare interrupt is still available, not sure about other timers


volatile float onTime = 0.0; // range (0,1], disable pwm for 0

void enablePWM(){
    cli();//stop interrupts

    digitalWrite(PORT_POS_UP, LOW);
    digitalWrite(PORT_POS_DOWN,LOW);
    digitalWrite(PORT_NEG_UP, LOW);
    digitalWrite(PORT_NEG_DOWN,LOW);

    //set timer2 interrupt 
    TCCR2A = 0;// set entire TCCR2A register to 0
    TCCR2B = 0;// same for TCCR2B
    TCNT2  = 0;//initialize counter value to 0

    // Set CS21 bit for 8 prescaler
    // duty cycle: (16*10^6) / (8*256) Hz = 7.8kHz
    TCCR2B |= (1 << CS21); 

    // set compare target, should update 
    // for n% signal OCR2A = (int) 256*n%
    //OCR2A = (uint8_t) 256.0*onTime;    
    OCR2A = 0;

    // enable timer compare interrupt and overflow interrupt
    TIMSK2 |= (1 << OCIE2A) | ( 1 << TOIE2);


    sei();//allow interrupts
  
}

void disablePWM(){
  
  
  cli();//stop interrupts
  //unset timer2 interrupt 
  TCCR2A = 0;// set entire TCCR2A register to 0
  TCCR2B = 0;// same for TCCR2B
  TCNT2  = 0;//initialize counter value to 0
  TIMSK2 = 0;

  sei();//allow interrupts
  
  digitalWrite(PORT_POS_UP, LOW);
  digitalWrite(PORT_POS_DOWN,LOW);
  digitalWrite(PORT_NEG_UP, LOW);
  digitalWrite(PORT_NEG_DOWN,LOW);
  
}


// Called at the falling edge of on-time, enter off-time configuration here
ISR(TIMER2_COMPA_vect){
// digital write takes ~6us to execute
// inline assembly takes <1us
// use with caution, though

/*
    digitalWrite(PORT_POS_UP, LOW);
    digitalWrite(PORT_NEG_UP, LOW);
    digitalWrite(PORT_POS_DOWN,HIGH);
    digitalWrite(PORT_NEG_DOWN,HIGH);
    digitalWrite(13,LOW);
*/
// 0-> POS_UP    
    asm (
      "cbi %0, %1 \n"
      : : "I" (_SFR_IO_ADDR(PORTB)), "I" (PORTB1)
    );

// 1-> POS_DOWN
    asm (
      "sbi %0, %1 \n"
      : : "I" (_SFR_IO_ADDR(PORTD)), "I" (PORTD6)
    );
 
}

// Beginning of each Duty Cycle, enter on-time configuration here
ISR(TIMER2_OVF_vect){
// Do this like a pro: write 1 to PINxN to toggle PORTxN
/*
    digitalWrite(PORT_NEG_UP, LOW);
    digitalWrite(PORT_POS_DOWN,LOW);
    digitalWrite(PORT_POS_UP, HIGH);
    digitalWrite(PORT_NEG_DOWN,HIGH);
    digitalWrite(13,HIGH);
*/
    
// 0-> POS_DOWN
    asm (
      "cbi %0, %1 \n"
      : : "I" (_SFR_IO_ADDR(PORTD)), "I" (PORTD6)
    );
    
// 1-> POS_UP
    asm (
      "sbi %0, %1 \n"
      : : "I" (_SFR_IO_ADDR(PORTB)), "I" (PORTB1)
    );
}

// forward only, range 0-1
#define MAX_H_BRIDGE_POWER 0.2
void setHbridgePower(float power){
    if (power<0.0 || power>1.0){
        disablePWM();
    } else{
        OCR2A = (uint8_t) 256.0*onTime*MAX_H_BRIDGE_POWER;
    }
    return;
}

// -------------- IMU code -------------

// class default I2C address is 0x68
// specific I2C addresses may be passed as a parameter here
// AD0 low = 0x68 (default for InvenSense evaluation board)
// AD0 high = 0x69
MPU6050 accelgyro;
//MPU6050 accelgyro(0x69); // <-- use for AD0 high

int16_t ax, ay, az;
int16_t gx, gy, gz;


//throttle variables
const int pinServo = 4;
const int pinDrive = 5;
Servo throttle;
Servo steer;

// values are in us (microseconds)
const float steeringRightLimit = 30.0;
const float steeringLeftLimit = -30.0;
const int leftBoundrySteeringServo = 1150;
const int rightBoundrySteeringServo = 1900;
const int midPointSteeringServo = 1550;
//const int minThrottleVal = 1500;
//
//static int throttleServoVal = 1500;
//static int steeringServoVal = 1550;

static unsigned long throttleTimestamp = 0;
static unsigned long steeringTimestamp = 0;

unsigned long carControlTimestamp = 0;
unsigned long voltageUpdateTimestamp = 0;
bool newCarControlMsg = false;

//ros variables
//pub,sub, in_buf, out_buf
ros::NodeHandle_<ArduinoHardware, 2, 2, 128, 300 > nh;

bool failsafe = false;

void readCarControlTopic(const rc_vip::CarControl& msg_CarControl) {
    carControlTimestamp = millis();
    newCarControlMsg = true;

    if (msg_CarControl.throttle < 0.001 || msg_CarControl.throttle > 1.0001) {
        //throttleServoVal = minThrottleVal;
        disablePWM();
        failsafe = true;
    } else {
        //needs a re-calibration
        //throttleServoVal = (int) map( msg_CarControl.throttle, 0.0, 1.0, 1460, 1450);

        // this works only when PWM is enabled
        // so failsafe can override this function
        setHbridgePower(msg_CarControl.throttle);
    }
    // COMMENT THIS OUT for moving motor
    //throttleServoVal = minThrottleVal;

    float tempSteering = constrain(msg_CarControl.steer_angle, steeringLeftLimit, steeringRightLimit);
    if ( tempSteering > 0.0 ){
        steeringServoVal = (int) map(tempSteering, 0.0, steeringRightLimit, 1550, 1900);
    } else if ( tempSteering < 0.0 ){
        steeringServoVal = (int) map(tempSteering, 0.0, steeringLeftLimit, 1550, 1150);
    } else {
        steeringServoVal = 1550;
    }
    steer.writeMicroseconds(steeringServoVal);

    return;
}


ros::Subscriber<rc_vip::CarControl> subCarControl("rc_vip/CarControl", &readCarControlTopic);
rc_vip::CarSensors carSensors_msg;
ros::Publisher pubCarSensors("rc_vip/CarSensors", &carSensors_msg);

void setup() {
    digitalWrite(PORT_POS_UP, LOW);
    digitalWrite(PORT_POS_DOWN,LOW);
    digitalWrite(PORT_NEG_UP, LOW);
    digitalWrite(PORT_NEG_DOWN,LOW);

    pinMode(PORT_POS_UP,OUTPUT);
    pinMode(PORT_POS_DOWN,OUTPUT);
    pinMode(PORT_NEG_UP,OUTPUT);
    pinMode(PORT_NEG_DOWN,OUTPUT);

    // tie one end to GND
    digitalWrite(PORT_NEG_DOWN,HIGH);

    pinMode(LED_PIN, OUTPUT);
    pinMode(VOLTAGEDIVIDER_PIN, INPUT);
    digitalWrite(LED_PIN, LOW);
    // join I2C bus (I2Cdev library doesn't do this automatically)
    #if I2CDEV_IMPLEMENTATION == I2CDEV_ARDUINO_WIRE
        Wire.begin();
    #elif I2CDEV_IMPLEMENTATION == I2CDEV_BUILTIN_FASTWIRE
        Fastwire::setup(400, true);
    #endif

    accelgyro.initialize();
    digitalWrite(LED_PIN, accelgyro.testConnection());


    nh.initNode();
    nh.advertise(pubCarSensors);
    nh.subscribe(subCarControl);

    while (!nh.connected())
        nh.spinOnce();

    //pinMode(pinDrive, OUTPUT);
    pinMode(pinServo, OUTPUT);
    //throttle.attach(pinDrive);
    steer.attach(pinServo);
   
    //ESC requires a low signal durin poweron to prevent accidental input
    //throttle.writeMicroseconds(minThrottleVal);
    //delay(300);
}

void loop() {

    //failsafe, if there's no new message for over 500ms, halt the motor
    if ( millis() - carControlTimestamp > 500 ){
        //throttle.writeMicroseconds(minThrottleVal);
        disablePWM();
        failsafe = true;
    } else if (failsafe){ // recover from failsafe
        enablePWM();
        failsafe = false;
    }

    // get new voltage every 100ms
    if ( millis()-voltageUpdateTimestamp>100 ){
        float voltage = (float)analogRead(VOLTAGEDIVIDER_PIN);
        // depends on experiment value
        voltage /= 16.27;
        carSensors_msg.voltage = voltage;
    }


    // read raw accel/gyro measurements from device
    // XXX this needs offsetting and scaling
    accelgyro.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);
    carSensors_msg.imu_ax = ax;
    carSensors_msg.imu_ay = ay;
    carSensors_msg.imu_az = az;

    carSensors_msg.imu_gx = gx;
    carSensors_msg.imu_gy = gy;
    carSensors_msg.imu_gz = gz;

    // TODO maybe add some throttling stuff?
    pubCarSensors.publish(&carSensors_msg);
    nh.spinOnce();

    // a loop rate too high may mess with Servo class's operation
    delay(10);
}
