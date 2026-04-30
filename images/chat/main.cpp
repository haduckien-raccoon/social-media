#include <Arduino.h>
#include <ESP32Servo.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include "Config.h" // Nhớ giữ lại file Config.h của bạn

// Thư viện micro-ROS
#include <micro_ros_arduino.h>
#include <stdio.h>
#include <rcl/rcl.h>
#include <rcl/error_handling.h>
#include <rclc/rclc.h>
#include <rclc/executor.h>
#include <geometry_msgs/msg/twist.h>
#include <sensor_msgs/msg/imu.h>
#include <std_msgs/msg/int32.h>
#include <time.h> // Thư viện hỗ trợ lấy thời gian thực

// ================= THIẾT LẬP ĐỐI TƯỢNG =================
Servo steerServo;
Adafruit_MPU6050 mpu;

// ================= BIẾN TOÀN CỤC =================
volatile State currentState = NORMAL;
volatile int target_speed = 0;    
volatile int target_steer = 90;   
unsigned long last_cmd_time = 0;
unsigned long last_encoder_time = 0;
long last_encoder_ticks_check = 0; 

// ================= BỘ LỌC NHIỄU ENCODER =================
volatile long encoder_ticks = 0;
volatile uint8_t last_state = 0;

inline uint8_t readEncoderState() {
    return (digitalRead(ENCODER_PIN_A) << 1) | digitalRead(ENCODER_PIN_B);
}

const int8_t lookup_table[16] = {
    0, -1,  1,  0,
    1,  0,  0, -1,
   -1,  0,  0,  1,
    0,  1, -1,  0
};

void IRAM_ATTR encoderISR() {
    uint8_t current_state = readEncoderState();
    uint8_t index = (last_state << 2) | current_state;
    encoder_ticks += lookup_table[index];
    last_state = current_state;
}

// ================= KHAI BÁO MICRO-ROS =================
rcl_subscription_t subscriber;
geometry_msgs__msg__Twist twist_msg;

rcl_publisher_t imu_publisher;
sensor_msgs__msg__Imu imu_msg;

rcl_publisher_t ticks_publisher;
std_msgs__msg__Int32 ticks_msg;

rclc_executor_t executor;
rclc_support_t support;
rcl_allocator_t allocator;
rcl_node_t node;
rcl_timer_t timer;

#define RCCHECK(fn) { rcl_ret_t temp_rc = fn; if((temp_rc != RCL_RET_OK)){}}
#define RCSOFTCHECK(fn) { rcl_ret_t temp_rc = fn; if((temp_rc != RCL_RET_OK)){}}

// ================= HÀM LẤY THỜI GIAN THỰC =================
// Hàm này đồng bộ hóa header.stamp của IMU với thời gian của Agent (Pi4B)
void sync_time() {
    unsigned long timeout_ms = 1000;
    rmw_uros_sync_session(timeout_ms); // Đồng bộ thời gian với host
}

// ================= CALLBACK MICRO-ROS =================
void twist_callback(const void * msgin) {
  const geometry_msgs__msg__Twist * msg = (const geometry_msgs__msg__Twist *)msgin;
  target_speed = msg->linear.x * 255.0; 
  target_steer = 90 - (msg->angular.z * 57.29); 
  target_steer = constrain(target_steer, 45, 135);
  last_cmd_time = millis();
}

void timer_callback(rcl_timer_t * timer, int64_t last_call_time) {
  RCLC_UNUSED(last_call_time);
  if (timer != NULL) {
    // 1. Gửi Ticks
    noInterrupts();
    ticks_msg.data = encoder_ticks;
    interrupts();
    RCSOFTCHECK(rcl_publish(&ticks_publisher, &ticks_msg, NULL));

    // 2. Gửi IMU có kèm Timestamp[cite: 2]
    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);

    // Lấy thời gian hiện tại từ hệ thống đã đồng bộ[cite: 2]
    struct timespec tv;
    clock_gettime(CLOCK_REALTIME, &tv); 
    
    imu_msg.header.stamp.sec = tv.tv_sec;
    imu_msg.header.stamp.nanosec = tv.tv_nsec;
    imu_msg.header.frame_id.data = (char*)"imu_link"; // Gán ID khung tọa độ[cite: 2]
    imu_msg.header.frame_id.size = strlen(imu_msg.header.frame_id.data);

    imu_msg.linear_acceleration.x = a.acceleration.x;
    imu_msg.linear_acceleration.y = a.acceleration.y;
    imu_msg.linear_acceleration.z = a.acceleration.z;
    imu_msg.angular_velocity.x = g.gyro.x;
    imu_msg.angular_velocity.y = g.gyro.y;
    imu_msg.angular_velocity.z = g.gyro.z;

    RCSOFTCHECK(rcl_publish(&imu_publisher, &imu_msg, NULL));
  }
}

// ================= CÁC TASK FREERTOS =================
void taskMicroROS(void *pvParameters) {
    while (1) {
        rclc_executor_spin_some(&executor, RCL_MS_TO_NS(10));
        if (millis() - last_cmd_time > 2000) {
            target_speed = 0;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

void taskMotorControl(void *pvParameters) {
    while (1) {
        steerServo.write(target_steer);
        if (currentState == EMERGENCY || target_speed == 0) {
            analogWrite(RPWM, 0); analogWrite(LPWM, 0);
        } else {
            if (target_speed > 0) {
                analogWrite(RPWM, target_speed); analogWrite(LPWM, 0);
            } else {
                analogWrite(RPWM, 0); analogWrite(LPWM, abs(target_speed)); 
            }
            if (millis() - last_encoder_time > STALL_TIMEOUT_MS) {
                noInterrupts();
                long current_ticks = encoder_ticks;
                interrupts();
                if (current_ticks == last_encoder_ticks_check) currentState = EMERGENCY;
                last_encoder_ticks_check = current_ticks;
                last_encoder_time = millis();
            }
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

void taskIMUSafety(void *pvParameters) {
    sensors_event_t a, g, temp;
    while (1) {
        mpu.getEvent(&a, &g, &temp);
        float tilt = abs(atan2(a.acceleration.y, a.acceleration.z) * 180 / PI);
        float totalAccel = sqrt(a.acceleration.x * a.acceleration.x + a.acceleration.y * a.acceleration.y);
        if (tilt > TILT_THRESHOLD || totalAccel > COLLISION_THRESHOLD * 9.8) currentState = EMERGENCY;
        vTaskDelay(pdMS_TO_TICKS(MPU_UPDATE_RATE_MS));
    }
}

void setup() {
    set_microros_transports(); 
    
    Wire.begin(SDA_PIN, SCL_PIN);
    if (mpu.begin()) mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
    
    pinMode(RPWM, OUTPUT); pinMode(LPWM, OUTPUT);
    pinMode(REN, OUTPUT); pinMode(LEN, OUTPUT);
    digitalWrite(REN, HIGH); digitalWrite(LEN, HIGH);
    
    steerServo.attach(SERVO_STEER_PIN);
    steerServo.write(90);
    
    pinMode(ENCODER_PIN_A, INPUT_PULLUP); pinMode(ENCODER_PIN_B, INPUT_PULLUP);
    last_state = readEncoderState();
    attachInterrupt(digitalPinToInterrupt(ENCODER_PIN_A), encoderISR, CHANGE);
    attachInterrupt(digitalPinToInterrupt(ENCODER_PIN_B), encoderISR, CHANGE);

    allocator = rcl_get_default_allocator();
    RCCHECK(rclc_support_init(&support, 0, NULL, &allocator));
    RCCHECK(rclc_node_init_default(&node, "esp32_ackermann_node", "", &support));

    // Thực hiện đồng bộ hóa thời gian ngay sau khi khởi tạo node[cite: 2]
    sync_time(); 

    RCCHECK(rclc_subscription_init_default(&subscriber, &node, ROSIDL_GET_MSG_TYPE_SUPPORT(geometry_msgs, msg, Twist), "/cmd_vel"));
    RCCHECK(rclc_publisher_init_default(&imu_publisher, &node, ROSIDL_GET_MSG_TYPE_SUPPORT(sensor_msgs, msg, Imu), "/imu/data_raw"));
    RCCHECK(rclc_publisher_init_default(&ticks_publisher, &node, ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, Int32), "/encoder_ticks"));

    RCCHECK(rclc_timer_init_default(&timer, &support, RCL_MS_TO_NS(50), timer_callback));

    RCCHECK(rclc_executor_init(&executor, &support.context, 2, &allocator));
    RCCHECK(rclc_executor_add_subscription(&executor, &subscriber, &twist_msg, &twist_callback, ON_NEW_DATA));
    RCCHECK(rclc_executor_add_timer(&executor, &timer));

    xTaskCreatePinnedToCore(taskMicroROS, "ROS2", 4096, NULL, 2, NULL, 1);
    xTaskCreatePinnedToCore(taskMotorControl, "Motor", 2048, NULL, 3, NULL, 1);
    xTaskCreatePinnedToCore(taskIMUSafety, "IMU", 2048, NULL, 4, NULL, 0);
}

void loop() {}