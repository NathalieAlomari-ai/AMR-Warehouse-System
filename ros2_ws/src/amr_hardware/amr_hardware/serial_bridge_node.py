"""
serial_bridge_node.py — Teensy 4.1 ↔ ROS 2 hardware bridge

Published topics
────────────────
  /wheel/odometry  (nav_msgs/Odometry)
      Pure encoder-only differential-drive kinematics.
      The yaw angle here is integrated from (v_right - v_left) / wheel_base —
      no IMU is mixed in — so it remains an independent source for the EKF.
      The EKF (robot_localization) subscribes here for linear velocity (vx).

  /imu/data  (sensor_msgs/Imu)
      BNO055 heading published as a proper Imu message.
      The BNO055 runs in OPERATION_MODE_IMUPLUS (accel + gyro, no magnetometer).
      Heading is relative (zeroed at boot); robot_localization handles this with
      imu0_relative: true so it subtracts the first reading automatically.
      Linear acceleration is unavailable from the current serial protocol;
      linear_acceleration_covariance[0] = -1 signals the EKF to ignore it.
      The EKF subscribes here for yaw orientation and yaw rate (vyaw).

TF
──
  publish_tf (default False): the EKF node owns odom → base_footprint.
  Set to True only if running without robot_localization (e.g. debugging).
  Having two nodes broadcast the same TF edge causes a ROS 2 TF conflict
  that makes the whole tree flap and corrupts SLAM localisation.

Serial protocol (from Teensy firmware, 20 Hz)
────────────────────────────────────────────
  Teensy → host: "L_RPM:<f>  R_RPM:<f>  Hdg:<f>  Dist:<f>  Lcnt:<i>  Rcnt:<i>\\n"
  Host → Teensy: "V <left_rpm> <right_rpm>\\n"
"""

import math
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu
import tf2_ros
import serial


class SerialBridgeNode(Node):
    def __init__(self):
        super().__init__('serial_bridge_node')

        # ── Parameters ───────────────────────────────────────────────────────
        self.declare_parameter('port',             '/dev/ttyACM0')
        self.declare_parameter('baudrate',         115200)
        self.declare_parameter('odom_frame',       'odom')
        # base_footprint: RSP handles the fixed base_footprint → base_link joint.
        self.declare_parameter('base_frame',       'base_footprint')
        self.declare_parameter('wheel_radius',     0.0625)
        self.declare_parameter('wheel_base',       0.65)
        self.declare_parameter('max_linear_accel', 1.0)    # m/s²
        self.declare_parameter('max_angular_accel', 2.0)   # rad/s²
        self.declare_parameter('ticks_per_rev',    1000)
        # EKF handoff: set False when robot_localization/ekf_node publishes TF.
        # Two nodes broadcasting odom → base_footprint simultaneously will
        # cause a TF conflict that corrupts SLAM and Nav2 localisation.
        self.declare_parameter('publish_tf',       False)

        port              = self.get_parameter('port').get_parameter_value().string_value
        baudrate          = self.get_parameter('baudrate').get_parameter_value().integer_value
        self._odom_frame  = self.get_parameter('odom_frame').get_parameter_value().string_value
        self._base_frame  = self.get_parameter('base_frame').get_parameter_value().string_value
        self._wheel_radius     = self.get_parameter('wheel_radius').get_parameter_value().double_value
        self._wheel_base       = self.get_parameter('wheel_base').get_parameter_value().double_value
        self._max_linear_accel = self.get_parameter('max_linear_accel').get_parameter_value().double_value
        self._max_angular_accel = self.get_parameter('max_angular_accel').get_parameter_value().double_value
        self._ticks_per_rev    = self.get_parameter('ticks_per_rev').get_parameter_value().integer_value
        self._publish_tf       = self.get_parameter('publish_tf').get_parameter_value().bool_value

        # ── Serial ───────────────────────────────────────────────────────────
        self._ser = None
        self._open_serial(port, baudrate)

        # ── Velocity smoother state ───────────────────────────────────────────
        self._target_linear   = 0.0
        self._target_angular  = 0.0
        self._current_linear  = 0.0
        self._current_angular = 0.0
        self._smoother_last_time = time.monotonic()

        # ── Encoder-only odometry state ───────────────────────────────────────
        # Yaw is integrated from differential-drive kinematics only.
        # The IMU heading is NOT mixed in here — keeping /wheel/odometry a truly
        # independent source so the EKF can weight the two streams separately.
        self._x   = 0.0
        self._y   = 0.0
        self._yaw = 0.0   # encoder-integrated heading (rad)

        # ── IMU state ─────────────────────────────────────────────────────────
        # Track previous raw heading for angular-velocity differentiation.
        self._prev_yaw_imu = None   # initialised on first telemetry packet

        self._prev_time  = None
        self._prev_lcnt: int | None = None
        self._prev_rcnt: int | None = None

        # ── Publishers ───────────────────────────────────────────────────────
        # Raw encoder odometry → EKF for linear velocity fusion
        self._odom_pub = self.create_publisher(Odometry, '/wheel/odometry', 10)
        # BNO055 heading → EKF for yaw / yaw-rate fusion
        self._imu_pub  = self.create_publisher(Imu, '/imu/data', 10)

        # TF broadcaster — only active when publish_tf is True
        if self._publish_tf:
            self._tf_broadcaster = tf2_ros.TransformBroadcaster(self)
        else:
            self._tf_broadcaster = None

        self.create_subscription(Twist, '/cmd_vel', self._cmd_vel_cb, 10)
        self.create_timer(0.01, self._read_serial)    # 100 Hz serial read
        self.create_timer(0.02, self._smoother_cb)    #  50 Hz velocity ramp

        self.get_logger().info(
            f'serial_bridge_node ready — port={port} baudrate={baudrate} '
            f'publish_tf={self._publish_tf}'
        )

    # ── Serial helpers ────────────────────────────────────────────────────────

    def _open_serial(self, port: str, baudrate: int) -> None:
        try:
            self._ser = serial.Serial(port, baudrate, timeout=0.01)
            self._ser.dtr = False
            time.sleep(0.1)
            self._ser.dtr = True
            self.get_logger().info(f'Opened serial port {port}')
        except serial.serialutil.SerialException as e:
            self.get_logger().error(f'Could not open serial port {port}: {e}')
            self._ser = None

    # ── Velocity command & smoother ───────────────────────────────────────────

    def _cmd_vel_cb(self, msg: Twist) -> None:
        self._target_linear  = msg.linear.x
        self._target_angular = msg.angular.z

    def _smoother_cb(self) -> None:
        now = time.monotonic()
        dt  = min(now - self._smoother_last_time, 0.1)
        self._smoother_last_time = now

        max_lin = self._max_linear_accel  * dt
        max_ang = self._max_angular_accel * dt

        diff_lin = self._target_linear - self._current_linear
        self._current_linear = (
            self._target_linear if abs(diff_lin) <= max_lin
            else self._current_linear + math.copysign(max_lin, diff_lin)
        )

        diff_ang = self._target_angular - self._current_angular
        self._current_angular = (
            self._target_angular if abs(diff_ang) <= max_ang
            else self._current_angular + math.copysign(max_ang, diff_ang)
        )

        if (self._current_linear  != 0.0 or self._current_angular  != 0.0 or
                self._target_linear != 0.0 or self._target_angular  != 0.0):
            self._send_velocity(self._current_linear, self._current_angular)

    def _send_velocity(self, linear: float, angular: float) -> None:
        if self._ser is None or not self._ser.is_open:
            return
        rpm_factor = 60.0 / (2.0 * math.pi * self._wheel_radius)
        l_rpm = (linear - angular * self._wheel_base / 2.0) * rpm_factor
        r_rpm = (linear + angular * self._wheel_base / 2.0) * rpm_factor
        packet = f'V {l_rpm:.2f} {r_rpm:.2f}\n'
        self.get_logger().debug(f'Sending: {packet.strip()}')
        try:
            self._ser.write(packet.encode('utf-8'))
        except serial.serialutil.SerialException as e:
            self.get_logger().error(f'Serial write failed: {e}')
            self._ser = None

    # ── Serial receive ────────────────────────────────────────────────────────

    def _read_serial(self) -> None:
        if self._ser is None or not self._ser.is_open:
            return
        try:
            line = self._ser.readline()
            if line:
                decoded = line.decode('utf-8', errors='replace').strip()
                if decoded:
                    self.get_logger().debug(f'Raw incoming: {decoded}')
                    self._parse_telemetry(decoded)
        except Exception as e:
            self.get_logger().error(f'Serial read error: {e}')

    # ── Telemetry parser ──────────────────────────────────────────────────────

    def _parse_telemetry(self, line: str) -> None:
        # الكود كان يتوقع 6 توكنز فقط، سنقوم بتبسيط القراءة لتكون أكثر قوة
        try:
            # تنظيف السطر من أي مسافات زائدة
            parts = line.replace('\t', ' ').split() 
            
            fields = {}
            for part in parts:
                if ':' in part:
                    key, value = part.split(':', 1)
                    fields[key] = value
            
            l_rpm   = float(fields['L_RPM'])
            r_rpm   = float(fields['R_RPM']) * -1.0 
            hdg_deg = float(fields['Hdg'])
            lcnt    = int(fields['Lcnt'])
            rcnt    = int(fields['Rcnt'])
            
            # (أكملي باقي منطق الحسابات كما كان في الكود الأصلي...)
            self._process_data(l_rpm, r_rpm, hdg_deg, lcnt, rcnt) 

        except Exception as e:
            # هذه ستخبرنا لو فشل الـ Parsing في المستقبل
            self.get_logger().warn(f"Parsing error: {e} | Line: {line}")
            return
        now = self.get_clock().now()

        if self._prev_time is None:
            self._prev_time    = now
            self._prev_lcnt    = lcnt
            self._prev_rcnt    = rcnt
            self._prev_yaw_imu = math.radians(hdg_deg)
            return

        dt = (now - self._prev_time).nanoseconds * 1e-9
        if dt <= 0.0:
            return
        self._prev_time = now

        # L_RPM fallback: firmware can report 0.0 while the encoder still ticks.
        delta_lcnt = lcnt - self._prev_lcnt
        if l_rpm == 0.0 and delta_lcnt != 0:
            l_rpm = (delta_lcnt / self._ticks_per_rev) / dt * 60.0

        self._prev_lcnt = lcnt
        self._prev_rcnt = rcnt

        rpm_to_ms = (2.0 * math.pi * self._wheel_radius) / 60.0
        v_left    = l_rpm * rpm_to_ms
        v_right   = r_rpm * rpm_to_ms

        # ── Encoder-only odometry (published on /wheel/odometry) ─────────────
        # Angular velocity from differential-drive kinematics — no IMU involved.
        # This keeps /wheel/odometry a clean, independent source for the EKF.
        vx        = (v_left + v_right) / 2.0
        omega_enc = (v_right - v_left) / self._wheel_base

        mid_yaw    = self._yaw + omega_enc * dt / 2.0   # midpoint integration
        self._x   += vx * math.cos(mid_yaw) * dt
        self._y   += vx * math.sin(mid_yaw) * dt
        self._yaw += omega_enc * dt
        self._yaw  = math.atan2(math.sin(self._yaw), math.cos(self._yaw))  # wrap

        # ── IMU heading (published on /imu/data) ──────────────────────────────
        # Publish the raw BNO055 heading with NO offset subtraction.
        # robot_localization handles the relative-mode zeroing via imu0_relative.
        yaw_imu_raw = math.radians(hdg_deg)
        # atan2 wrap-around handles the 0°/360° boundary cleanly
        dyaw_imu    = math.atan2(
            math.sin(yaw_imu_raw - self._prev_yaw_imu),
            math.cos(yaw_imu_raw - self._prev_yaw_imu),
        )
        vyaw_imu             = dyaw_imu / dt
        self._prev_yaw_imu   = yaw_imu_raw

        self._publish_wheel_odom(now, vx, omega_enc)
        self._publish_imu(now, yaw_imu_raw, vyaw_imu)

    # ── /wheel/odometry publisher ─────────────────────────────────────────────

    def _publish_wheel_odom(self, stamp, vx: float, omega: float) -> None:
        ros_stamp = stamp.to_msg()
        qz = math.sin(self._yaw / 2.0)
        qw = math.cos(self._yaw / 2.0)

        odom = Odometry()
        odom.header.stamp    = ros_stamp
        odom.header.frame_id = self._odom_frame
        odom.child_frame_id  = self._base_frame

        odom.pose.pose.position.x    = self._x
        odom.pose.pose.position.y    = self._y
        odom.pose.pose.orientation.z = qz
        odom.pose.pose.orientation.w = qw

        # Pose covariance (6×6 row-major, order: x y z roll pitch yaw)
        # High yaw covariance: gearbox backlash makes encoder heading unreliable.
        # The EKF ignores pose (odom0_config has all pose cols = false), so these
        # values are informational only — but set them correctly for diagnostics.
        odom.pose.covariance[0]  = 0.01    # x        — moderate confidence
        odom.pose.covariance[7]  = 0.01    # y        — moderate confidence
        odom.pose.covariance[14] = 1.0e6   # z        — 2D, unused
        odom.pose.covariance[21] = 1.0e6   # roll     — 2D, unused
        odom.pose.covariance[28] = 1.0e6   # pitch    — 2D, unused
        odom.pose.covariance[35] = 0.5     # yaw      — LOW confidence: slip/backlash

        odom.twist.twist.linear.x  = vx
        odom.twist.twist.angular.z = omega

        # Twist covariance (6×6 row-major, order: vx vy vz vroll vpitch vyaw)
        # vx is the primary fused quantity — encoders are reliable for linear speed.
        # vyaw from encoders is less confident than the IMU gyro, so we weight it low.
        odom.twist.covariance[0]  = 0.005  # vx   — high confidence from encoders
        odom.twist.covariance[7]  = 1.0e6  # vy   — non-holonomic, should be ~0
        odom.twist.covariance[14] = 1.0e6  # vz   — 2D, unused
        odom.twist.covariance[21] = 1.0e6  # vroll  — 2D, unused
        odom.twist.covariance[28] = 1.0e6  # vpitch — 2D, unused
        odom.twist.covariance[35] = 0.2    # vyaw — less confident than IMU gyro

        self._odom_pub.publish(odom)

        # TF is only broadcast when publish_tf is True (i.e. running without EKF).
        # When robot_localization/ekf_node is running, it owns odom → base_footprint.
        if self._tf_broadcaster is not None:
            tf_msg = TransformStamped()
            tf_msg.header.stamp    = ros_stamp
            tf_msg.header.frame_id = self._odom_frame
            tf_msg.child_frame_id  = self._base_frame
            tf_msg.transform.translation.x = self._x
            tf_msg.transform.translation.y = self._y
            tf_msg.transform.rotation.z    = qz
            tf_msg.transform.rotation.w    = qw
            self._tf_broadcaster.sendTransform(tf_msg)

    # ── /imu/data publisher ───────────────────────────────────────────────────

    def _publish_imu(self, stamp, yaw: float, vyaw: float) -> None:
        """
        Publish BNO055 heading as sensor_msgs/Imu for the EKF.

        The BNO055 is in OPERATION_MODE_IMUPLUS (accel + gyro, no magnetometer).
        Heading is the raw board output — NOT offset to zero — because
        robot_localization imu0_relative: true does that subtraction internally.

        Covariance conventions used here:
          - Roll / pitch are unknown (value = 1e6, treated as "don't use")
          - Yaw / vyaw are from the BNO055 IMUPLUS fusion: high short-term confidence
          - linear_acceleration_covariance[0] = -1 signals EKF to IGNORE linear accel
            (it is unavailable from the current 6-field serial protocol)
        """
        imu = Imu()
        imu.header.stamp    = stamp.to_msg()
        imu.header.frame_id = self._base_frame

        # Orientation: pure yaw quaternion (roll=0, pitch=0)
        qz = math.sin(yaw / 2.0)
        qw = math.cos(yaw / 2.0)
        imu.orientation.x = 0.0
        imu.orientation.y = 0.0
        imu.orientation.z = qz
        imu.orientation.w = qw

        # Orientation covariance (3×3 row-major, order: roll pitch yaw)
        # BNO055 gyro-fused yaw has excellent short-term accuracy in IMUPLUS mode.
        # Roll/pitch are unknown from the serial protocol → set to large value.
        imu.orientation_covariance[0] = 1.0e6   # roll  — unknown
        imu.orientation_covariance[4] = 1.0e6   # pitch — unknown
        imu.orientation_covariance[8] = 0.001   # yaw   — HIGH confidence (IMUPLUS gyro)

        # Angular velocity: only yaw rate available (differentiated from heading)
        imu.angular_velocity.x = 0.0
        imu.angular_velocity.y = 0.0
        imu.angular_velocity.z = vyaw

        # Angular velocity covariance (3×3 row-major, order: x y z)
        # Yaw rate from heading differentiation: slightly noisier than raw gyro
        # but still far better than encoder-derived angular velocity.
        imu.angular_velocity_covariance[0] = 1.0e6   # vroll  — unknown
        imu.angular_velocity_covariance[4] = 1.0e6   # vpitch — unknown
        imu.angular_velocity_covariance[8] = 0.005   # vyaw   — moderate confidence

        # Linear acceleration: unavailable from the 6-field serial protocol.
        # Setting covariance[0] = -1 is the robot_localization convention to signal
        # "this sensor does not provide linear acceleration — do not fuse it."
        imu.linear_acceleration_covariance[0] = -1.0

        self._imu_pub.publish(imu)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def destroy_node(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = SerialBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
