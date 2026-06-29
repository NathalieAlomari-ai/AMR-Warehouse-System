"""
robot_navigation.launch.py — Full autonomous navigation bringup

Starts:
  1. bringup.launch.py     — hardware (serial_bridge, EKF, LiDAR, RSP)
  2. navigation.launch.py  — AMCL localization + Nav2 stack + twist_mux
  3. RViz2                 — navigation visualization config

Usage:
  ros2 launch amr_bringup robot_navigation.launch.py

In RViz:
  1. Click "2D Pose Estimate" and drag to set robot's starting position on the map
  2. Wait for AMCL particle cloud to converge
  3. Click "Nav2 Goal" (in Nav2 panel) and click a goal on the map
  4. Joystick overrides Nav2 at any time (twist_mux priority 100 vs 10)
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    bringup_share = get_package_share_directory('amr_bringup')
    nav_share     = get_package_share_directory('amr_navigation')

    bringup = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_share, 'launch', 'bringup.launch.py')
        )
    )

    navigation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav_share, 'launch', 'navigation.launch.py')
        )
    )

    rviz = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        arguments=['-d', os.path.join(nav_share, 'rviz', 'navigation.rviz')],
        output='screen',
    )

    return LaunchDescription([
        bringup,
        navigation,
        rviz,
    ])
