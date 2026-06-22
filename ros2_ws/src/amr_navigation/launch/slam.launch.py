import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    nav_share   = get_package_share_directory('amr_navigation')
    slam_config = os.path.join(nav_share, 'config', 'mapper_params_online_async.yaml')

    # fake_odom removed — real odom → base_footprint TF is now broadcast by
    # serial_bridge_node using wheel-encoder differential-drive kinematics.

    slam = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        parameters=[slam_config, {'use_sim_time': False}],
    )

    return LaunchDescription([
        slam,
    ])
