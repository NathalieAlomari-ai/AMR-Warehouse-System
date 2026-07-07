"""Launch the mission coordinator, optionally with the vision stub.

Usage:
  # Full stub run (no camera, no YOLO) — good for testing the sequence:
  ros2 launch amr_coordinator coordinator.launch.py use_stub:=true

  # Real run — start the real amr_vision node separately instead of the stub:
  ros2 launch amr_coordinator coordinator.launch.py use_stub:=false

This launches ONLY the coordinator (+stub). serial_bridge_node, Nav2 and the
robot bringup are expected to already be running.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    use_stub = LaunchConfiguration('use_stub')

    return LaunchDescription([
        DeclareLaunchArgument(
            'use_stub', default_value='true',
            description='Start vision_stub instead of the real YOLO vision node'),

        Node(
            package='amr_coordinator',
            executable='coordinator_node',
            name='amr_coordinator',
            output='screen',
        ),

        Node(
            package='amr_coordinator',
            executable='vision_stub',
            name='vision_stub',
            output='screen',
            condition=IfCondition(use_stub),
        ),
    ])
