#!/usr/bin/env python3
"""
Navigate the robot to a named waypoint from waypoints.yaml.

Usage (run on laptop while robot navigation stack is running):
  ros2 run amr_navigation waypoint_navigator.py shelf_A
  ros2 run amr_navigation waypoint_navigator.py --list
"""

import sys
import math
import os
import yaml
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.duration import Duration
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped

WAYPOINTS_FILE = os.path.expanduser(
    '~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/config/waypoints.yaml')


def yaw_to_quat(yaw):
    return math.sin(yaw / 2.0), math.cos(yaw / 2.0)


class WaypointNavigator(Node):
    def __init__(self):
        super().__init__('waypoint_navigator')
        self._client = ActionClient(self, NavigateToPose, 'navigate_to_pose')

    def go(self, name, x, y, yaw):
        self.get_logger().info(
            f'Sending robot to "{name}" (x={x:.3f}, y={y:.3f}, yaw={yaw:.3f})')

        self.get_logger().info('Waiting for navigate_to_pose action server...')
        if not self._client.wait_for_server(timeout_sec=30.0):
            self.get_logger().error(
                'navigate_to_pose action server not available after 30s. Is the robot running?')
            return False

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(x)
        goal.pose.pose.position.y = float(y)
        qz, qw = yaw_to_quat(float(yaw))
        goal.pose.pose.orientation.z = qz
        goal.pose.pose.orientation.w = qw

        send_future = self._client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, send_future)
        handle = send_future.result()

        if not handle.accepted:
            self.get_logger().error('Goal was rejected by Nav2')
            return False

        self.get_logger().info('Goal accepted — robot is on its way...')
        result_future = handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)
        self.get_logger().info(f'Arrived at "{name}"!')
        return True


def load_waypoints():
    if not os.path.exists(WAYPOINTS_FILE):
        print(f'Waypoints file not found: {WAYPOINTS_FILE}')
        sys.exit(1)
    with open(WAYPOINTS_FILE) as f:
        data = yaml.safe_load(f) or {}
    wps = data.get('waypoints') or {}
    return wps


def main():
    if len(sys.argv) < 2:
        print('Usage:')
        print('  waypoint_navigator.py <waypoint_name>')
        print('  waypoint_navigator.py --list')
        sys.exit(1)

    waypoints = load_waypoints()

    if sys.argv[1] == '--list':
        if not waypoints:
            print('No waypoints saved yet. Use waypoint_saver.py to save some.')
        else:
            print('Saved waypoints:')
            for name, wp in sorted(waypoints.items()):
                print(f'  {name:20s}  x={wp["x"]:7.3f}  y={wp["y"]:7.3f}  yaw={wp["yaw"]:6.3f}')
        sys.exit(0)

    name = sys.argv[1]
    if name not in waypoints:
        print(f'Waypoint "{name}" not found.')
        print(f'Available: {", ".join(sorted(waypoints.keys())) or "none"}')
        sys.exit(1)

    wp = waypoints[name]
    rclpy.init()
    node = WaypointNavigator()
    ok = node.go(name, wp['x'], wp['y'], wp['yaw'])
    node.destroy_node()
    rclpy.shutdown()
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
