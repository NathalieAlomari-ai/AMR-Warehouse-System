#!/usr/bin/env python3
"""
Send the robot through a sequence of named waypoints from waypoints.yaml,
using Nav2's waypoint_follower (pauses at each stop per wait_at_waypoint config).

Usage (run on laptop while robot navigation stack is running):
  ros2 run amr_navigation mission_runner.py shelf_A drop_off home
  ros2 run amr_navigation mission_runner.py --list
"""

import sys
import math
import os
import yaml
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import FollowWaypoints
from geometry_msgs.msg import PoseStamped

WAYPOINTS_FILE = os.path.expanduser(
    '~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/config/waypoints.yaml')


def yaw_to_quat(yaw):
    return math.sin(yaw / 2.0), math.cos(yaw / 2.0)


def load_waypoints():
    if not os.path.exists(WAYPOINTS_FILE):
        print(f'Waypoints file not found: {WAYPOINTS_FILE}')
        sys.exit(1)
    with open(WAYPOINTS_FILE) as f:
        data = yaml.safe_load(f) or {}
    return data.get('waypoints') or {}


class MissionRunner(Node):
    def __init__(self):
        super().__init__('mission_runner')
        self._client = ActionClient(self, FollowWaypoints, 'follow_waypoints')

    def run(self, names, waypoints):
        self.get_logger().info('Waiting for follow_waypoints action server...')
        if not self._client.wait_for_server(timeout_sec=30.0):
            self.get_logger().error(
                'follow_waypoints action server not available after 30s. Is the robot running?')
            return False

        goal = FollowWaypoints.Goal()
        for name in names:
            wp = waypoints[name]
            pose = PoseStamped()
            pose.header.frame_id = 'map'
            pose.header.stamp = self.get_clock().now().to_msg()
            pose.pose.position.x = float(wp['x'])
            pose.pose.position.y = float(wp['y'])
            qz, qw = yaw_to_quat(float(wp['yaw']))
            pose.pose.orientation.z = qz
            pose.pose.orientation.w = qw
            goal.poses.append(pose)

        self.get_logger().info(
            f'Sending mission: {" -> ".join(names)} ({len(names)} stops)')

        send_future = self._client.send_goal_async(goal, feedback_callback=self._feedback_cb)
        rclpy.spin_until_future_complete(self, send_future)
        handle = send_future.result()

        if not handle.accepted:
            self.get_logger().error('Mission was rejected by Nav2')
            return False

        self._names = names
        self.get_logger().info('Mission accepted — robot is on its way...')
        result_future = handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)
        result = result_future.result().result

        if result.missed_waypoints:
            missed_names = [names[i] for i in result.missed_waypoints if i < len(names)]
            self.get_logger().warn(
                f'Mission finished with missed stops: {", ".join(missed_names)}')
            return False

        self.get_logger().info('Mission complete — all stops reached!')
        return True

    def _feedback_cb(self, feedback_msg):
        idx = feedback_msg.feedback.current_waypoint
        if idx < len(self._names):
            self.get_logger().info(
                f'Heading to stop {idx + 1}/{len(self._names)}: "{self._names[idx]}"')


def main():
    if len(sys.argv) < 2:
        print('Usage:')
        print('  mission_runner.py <waypoint_name> [<waypoint_name> ...]')
        print('  mission_runner.py --list')
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

    names = sys.argv[1:]
    unknown = [n for n in names if n not in waypoints]
    if unknown:
        print(f'Waypoint(s) not found: {", ".join(unknown)}')
        print(f'Available: {", ".join(sorted(waypoints.keys())) or "none"}')
        sys.exit(1)

    rclpy.init()
    node = MissionRunner()
    ok = node.run(names, waypoints)
    node.destroy_node()
    rclpy.shutdown()
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
