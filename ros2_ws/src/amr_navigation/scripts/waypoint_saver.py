#!/usr/bin/env python3
"""
Save the robot's current AMCL pose as a named waypoint.

Usage (run on laptop while robot is localized):
  ros2 run amr_navigation waypoint_saver.py shelf_A
  ros2 run amr_navigation waypoint_saver.py home
"""

import sys
import math
import os
import yaml
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseWithCovarianceStamped

WAYPOINTS_FILE = os.path.expanduser(
    '~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/config/waypoints.yaml')


def quat_to_yaw(qz, qw):
    return 2.0 * math.atan2(float(qz), float(qw))


class WaypointSaver(Node):
    def __init__(self, name):
        super().__init__('waypoint_saver')
        self._name = name
        self._done = False
        self._sub = self.create_subscription(
            PoseWithCovarianceStamped, '/amcl_pose', self._cb, 1)
        self.get_logger().info(f'Waiting for AMCL pose to save as "{name}"...')

    def _cb(self, msg):
        if self._done:
            return
        self._done = True

        x   = msg.pose.pose.position.x
        y   = msg.pose.pose.position.y
        yaw = quat_to_yaw(msg.pose.pose.orientation.z,
                          msg.pose.pose.orientation.w)

        if os.path.exists(WAYPOINTS_FILE):
            with open(WAYPOINTS_FILE) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}

        if 'waypoints' not in data or data['waypoints'] is None:
            data['waypoints'] = {}

        data['waypoints'][self._name] = {
            'x':   round(x,   3),
            'y':   round(y,   3),
            'yaw': round(yaw, 3),
        }

        with open(WAYPOINTS_FILE, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=True)

        self.get_logger().info(
            f'Saved "{self._name}": x={x:.3f}  y={y:.3f}  yaw={yaw:.3f}')
        self.get_logger().info(f'File: {WAYPOINTS_FILE}')


def main():
    if len(sys.argv) < 2:
        print('Usage: waypoint_saver.py <waypoint_name>')
        sys.exit(1)

    rclpy.init()
    node = WaypointSaver(sys.argv[1])

    while rclpy.ok() and not node._done:
        rclpy.spin_once(node, timeout_sec=0.1)

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
