import math
import re
import threading

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry
import tf2_ros

import serial
import serial.serialutil

# Matches: L_RPM: <val> \t R_RPM: <val> \t Hdg: <val> \t Dist: <val> \t Lcnt: <val> \t Rcnt: <val>
_TELEMETRY_RE = re.compile(
    r'L_RPM:\s*([\-\d.]+)\s+R_RPM:\s*([\-\d.]+)\s+Hdg:\s*([\-\d.]+)\s+'
    r'Dist:\s*([\-\d.]+)\s+Lcnt:\s*([\-\d.]+)\s+Rcnt:\s*([\-\d.]+)'
)


class SerialBridgeNode(Node):
    def __init__(self):
        super().__init__('serial_bridge_node')

        self.declare_parameter('port', '/dev/ttyACM0')
        self.declare_parameter('baudrate', 115200)
        self.declare_parameter('odom_frame', 'odom')
        self.declare_parameter('base_frame', 'base_link')

        port = self.get_parameter('port').get_parameter_value().string_value
        baudrate = self.get_parameter('baudrate').get_parameter_value().integer_value
        self._odom_frame = self.get_parameter('odom_frame').get_parameter_value().string_value
        self._base_frame = self.get_parameter('base_frame').get_parameter_value().string_value

        self._ser = None
        self._ser_lock = threading.Lock()
        self._open_serial(port, baudrate)

        # Odometry state
        self._x = 0.0
        self._y = 0.0
        self._prev_dist = None   # metres, cumulative from Teensy
        self._prev_hdg = None    # degrees
        self._prev_time = None

        self._odom_pub = self.create_publisher(Odometry, '/odom', 10)
        self._tf_broadcaster = tf2_ros.TransformBroadcaster(self)

        self.create_subscription(Twist, '/cmd_vel', self._cmd_vel_cb, 10)

        # Background thread reads serial without blocking the ROS executor
        self._stop_event = threading.Event()
        self._reader_thread = threading.Thread(target=self._serial_reader, daemon=True)
        self._reader_thread.start()

        self.get_logger().info(
            f'serial_bridge_node ready — port={port} baudrate={baudrate}'
        )

    # ------------------------------------------------------------------
    # Serial helpers
    # ------------------------------------------------------------------

    def _open_serial(self, port: str, baudrate: int) -> None:
        try:
            self._ser = serial.Serial(port, baudrate, timeout=1.0)
            self.get_logger().info(f'Opened serial port {port}')
        except serial.serialutil.SerialException as e:
            self.get_logger().error(f'Could not open serial port {port}: {e}')
            self._ser = None

    def _cmd_vel_cb(self, msg: Twist) -> None:
        if self._ser is None or not self._ser.is_open:
            self.get_logger().warn(
                'Serial port not open — dropping cmd_vel',
                throttle_duration_sec=5.0,
            )
            return

        linear = msg.linear.x
        angular = msg.angular.z
        packet = f'<{linear:.4f},{angular:.4f}>\n'

        try:
            with self._ser_lock:
                self._ser.write(packet.encode('utf-8'))
        except serial.serialutil.SerialException as e:
            self.get_logger().error(f'Serial write failed: {e}')
            self._ser = None

    # ------------------------------------------------------------------
    # Background serial reader
    # ------------------------------------------------------------------

    def _serial_reader(self) -> None:
        while not self._stop_event.is_set():
            if self._ser is None or not self._ser.is_open:
                self._stop_event.wait(0.5)
                continue

            try:
                with self._ser_lock:
                    line = self._ser.readline()
            except serial.serialutil.SerialException as e:
                self.get_logger().error(f'Serial read failed: {e}')
                self._ser = None
                continue

            if not line:
                continue

            try:
                decoded = line.decode('utf-8', errors='replace').strip()
            except Exception:
                continue

            self._parse_telemetry(decoded)

    # ------------------------------------------------------------------
    # Telemetry parsing + odometry
    # ------------------------------------------------------------------

    def _parse_telemetry(self, line: str) -> None:
        m = _TELEMETRY_RE.search(line)
        if m is None:
            return

        try:
            hdg_deg = float(m.group(3))
            dist_m = float(m.group(4))
        except ValueError:
            return

        now = self.get_clock().now()

        # First reading — initialise state and return
        if self._prev_time is None:
            self._prev_dist = dist_m
            self._prev_hdg = hdg_deg
            self._prev_time = now
            return

        dt = (now - self._prev_time).nanoseconds * 1e-9
        if dt <= 0.0:
            return

        delta_dist = dist_m - self._prev_dist
        hdg_rad = math.radians(hdg_deg)
        prev_hdg_rad = math.radians(self._prev_hdg)
        delta_hdg_rad = hdg_rad - prev_hdg_rad

        # Integrate position using the current heading
        self._x += delta_dist * math.cos(hdg_rad)
        self._y += delta_dist * math.sin(hdg_rad)

        linear_vel = delta_dist / dt
        angular_vel = delta_hdg_rad / dt

        self._prev_dist = dist_m
        self._prev_hdg = hdg_deg
        self._prev_time = now

        self._publish_odom(now, hdg_rad, linear_vel, angular_vel)

    def _publish_odom(self, stamp, yaw: float, linear_vel: float, angular_vel: float) -> None:
        ros_stamp = stamp.to_msg()
        qz = math.sin(yaw / 2.0)
        qw = math.cos(yaw / 2.0)

        # Odometry message
        odom = Odometry()
        odom.header.stamp = ros_stamp
        odom.header.frame_id = self._odom_frame
        odom.child_frame_id = self._base_frame

        odom.pose.pose.position.x = self._x
        odom.pose.pose.position.y = self._y
        odom.pose.pose.position.z = 0.0
        odom.pose.pose.orientation.x = 0.0
        odom.pose.pose.orientation.y = 0.0
        odom.pose.pose.orientation.z = qz
        odom.pose.pose.orientation.w = qw

        odom.twist.twist.linear.x = linear_vel
        odom.twist.twist.angular.z = angular_vel

        # Diagonal covariance (position xyz, rotation xyz)
        odom.pose.covariance[0] = 0.01   # x
        odom.pose.covariance[7] = 0.01   # y
        odom.pose.covariance[35] = 0.05  # yaw
        odom.twist.covariance[0] = 0.01  # vx
        odom.twist.covariance[35] = 0.05 # vyaw

        self._odom_pub.publish(odom)

        # TF transform odom → base_link
        tf_msg = TransformStamped()
        tf_msg.header.stamp = ros_stamp
        tf_msg.header.frame_id = self._odom_frame
        tf_msg.child_frame_id = self._base_frame
        tf_msg.transform.translation.x = self._x
        tf_msg.transform.translation.y = self._y
        tf_msg.transform.translation.z = 0.0
        tf_msg.transform.rotation.x = 0.0
        tf_msg.transform.rotation.y = 0.0
        tf_msg.transform.rotation.z = qz
        tf_msg.transform.rotation.w = qw

        self._tf_broadcaster.sendTransform(tf_msg)

    # ------------------------------------------------------------------

    def destroy_node(self) -> None:
        self._stop_event.set()
        self._reader_thread.join(timeout=2.0)
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
