import math
import time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry
import tf2_ros
import serial

class SerialBridgeNode(Node):
    def __init__(self):
        super().__init__('serial_bridge_node')

        self.declare_parameter('port', '/dev/ttyACM0')
        self.declare_parameter('baudrate', 115200)
        self.declare_parameter('odom_frame', 'odom')
        self.declare_parameter('base_frame', 'base_link')
        self.declare_parameter('wheel_radius', 0.0625)
        self.declare_parameter('wheel_base', 0.65)
        self.declare_parameter('max_linear_accel', 1.0)   # m/s² — stops in ~0.5 s from 0.5 m/s
        self.declare_parameter('max_angular_accel', 2.0)  # rad/s² — stops in ~0.5 s from 1.0 rad/s

        port = self.get_parameter('port').get_parameter_value().string_value
        baudrate = self.get_parameter('baudrate').get_parameter_value().integer_value
        self._odom_frame = self.get_parameter('odom_frame').get_parameter_value().string_value
        self._base_frame = self.get_parameter('base_frame').get_parameter_value().string_value
        self._wheel_radius = self.get_parameter('wheel_radius').get_parameter_value().double_value
        self._wheel_base = self.get_parameter('wheel_base').get_parameter_value().double_value
        self._max_linear_accel = self.get_parameter('max_linear_accel').get_parameter_value().double_value
        self._max_angular_accel = self.get_parameter('max_angular_accel').get_parameter_value().double_value

        self._ser = None
        self._open_serial(port, baudrate)

        # Velocity smoother state
        self._target_linear = 0.0
        self._target_angular = 0.0
        self._current_linear = 0.0
        self._current_angular = 0.0
        self._smoother_last_time = time.monotonic()

        # Odometry state
        self._x = 0.0
        self._y = 0.0
        self._yaw = 0.0
        self._hdg_offset = 0.0   # IMU heading at startup, used to anchor odom frame
        self._prev_time = None

        self._odom_pub = self.create_publisher(Odometry, '/odom', 10)
        self._tf_broadcaster = tf2_ros.TransformBroadcaster(self)
        self.create_subscription(Twist, '/cmd_vel', self._cmd_vel_cb, 10)

        # التخلص من الـ Threads المعقدة واستخدام مؤقت ROS2 الآمن (100Hz)
        self.create_timer(0.01, self._read_serial)
        self.create_timer(0.02, self._smoother_cb)  # 50 Hz velocity ramp

        self.get_logger().info(f'serial_bridge_node ready — port={port} baudrate={baudrate}')

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

    def _cmd_vel_cb(self, msg: Twist) -> None:
        # Only update targets; the smoother timer ramps and sends.
        self._target_linear = msg.linear.x
        self._target_angular = msg.angular.z

    def _smoother_cb(self) -> None:
        now = time.monotonic()
        dt = min(now - self._smoother_last_time, 0.1)  # clamp after pauses
        self._smoother_last_time = now

        max_lin = self._max_linear_accel * dt
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

        # Send while moving or while still ramping down to zero
        if (self._current_linear != 0.0 or self._current_angular != 0.0 or
                self._target_linear != 0.0 or self._target_angular != 0.0):
            self._send_velocity(self._current_linear, self._current_angular)

    def _send_velocity(self, linear: float, angular: float) -> None:
        if self._ser is None or not self._ser.is_open:
            return
        # Differential-drive: convert (m/s, rad/s) → individual wheel RPMs
        rpm_factor = 60.0 / (2.0 * math.pi * self._wheel_radius)
        l_rpm = (linear - angular * self._wheel_base / 2.0) * rpm_factor
        r_rpm = (linear + angular * self._wheel_base / 2.0) * rpm_factor
        # Firmware protocol: "V <left_rpm> <right_rpm>\n"  (see main.cpp line 17)
        packet = f'V {l_rpm:.2f} {r_rpm:.2f}\n'
        self.get_logger().info(f'Sending: {packet.strip()}')
        try:
            self._ser.write(packet.encode('utf-8'))
        except serial.serialutil.SerialException as e:
            self.get_logger().error(f'Serial write failed: {e}')
            self._ser = None

    def _read_serial(self) -> None:
        if self._ser is None or not self._ser.is_open:
            return

        try:
            # قراءة مباشرة بدون شروط تعجيزية
            line = self._ser.readline()
            if line:
                decoded = line.decode('utf-8', errors='replace').strip()
                if decoded:
                    self.get_logger().info(f'Raw incoming: {decoded}')
                    self._parse_telemetry(decoded)
        except Exception as e:
            self.get_logger().error(f'Serial read error: {e}')

    def _parse_telemetry(self, line: str) -> None:
        # Expected format: L_RPM:<f> R_RPM:<f> Hdg:<f> Dist:<f> Lcnt:<i> Rcnt:<i>
        fields: dict[str, str] = {}
        for token in line.split():
            if ':' in token:
                key, _, value = token.partition(':')
                fields[key] = value

        try:
            l_rpm = float(fields['L_RPM'])
            r_rpm = float(fields['R_RPM'])
            hdg_deg = float(fields['Hdg'])
            # Dist and Lcnt/Rcnt are parsed but reserved for future sensor-fusion use
        except (KeyError, ValueError):
            return

        now = self.get_clock().now()

        if self._prev_time is None:
            self._prev_time = now
            # Anchor the odom frame to the robot's heading at startup
            self._hdg_offset = math.radians(hdg_deg)
            return

        dt = (now - self._prev_time).nanoseconds * 1e-9
        if dt <= 0.0:
            return
        self._prev_time = now

        # IMU heading relative to startup orientation, normalized to [-π, π]
        raw_yaw = math.radians(hdg_deg) - self._hdg_offset
        yaw = math.atan2(math.sin(raw_yaw), math.cos(raw_yaw))

        # Angular velocity from heading delta; atan2 handles ±180° wrap-around
        dyaw = math.atan2(math.sin(yaw - self._yaw), math.cos(yaw - self._yaw))
        angular_vel = dyaw / dt

        rpm_to_ms = (2.0 * math.pi * self._wheel_radius) / 60.0
        v_left  = l_rpm * rpm_to_ms
        v_right = r_rpm * rpm_to_ms

        # Encoder-only displacement — decoupled from the IMU heading source
        ds = (v_left + v_right) / 2.0 * dt

        # Project encoder displacement onto the IMU-derived heading midpoint
        mid_yaw = self._yaw + dyaw / 2.0
        self._x += ds * math.cos(mid_yaw)
        self._y += ds * math.sin(mid_yaw)
        self._yaw = yaw

        self._publish_odom(now, self._yaw, ds / dt, angular_vel)

    def _publish_odom(self, stamp, yaw: float, linear_vel: float, angular_vel: float) -> None:
        ros_stamp = stamp.to_msg()
        qz = math.sin(yaw / 2.0)
        qw = math.cos(yaw / 2.0)

        odom = Odometry()
        odom.header.stamp = ros_stamp
        odom.header.frame_id = self._odom_frame
        odom.child_frame_id = self._base_frame

        odom.pose.pose.position.x = self._x
        odom.pose.pose.position.y = self._y
        odom.pose.pose.orientation.z = qz
        odom.pose.pose.orientation.w = qw
        odom.twist.twist.linear.x = linear_vel
        odom.twist.twist.angular.z = angular_vel

        self._odom_pub.publish(odom)

        tf_msg = TransformStamped()
        tf_msg.header.stamp = ros_stamp
        tf_msg.header.frame_id = self._odom_frame
        tf_msg.child_frame_id = self._base_frame
        tf_msg.transform.translation.x = self._x
        tf_msg.transform.translation.y = self._y
        tf_msg.transform.rotation.z = qz
        tf_msg.transform.rotation.w = qw

        self._tf_broadcaster.sendTransform(tf_msg)

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