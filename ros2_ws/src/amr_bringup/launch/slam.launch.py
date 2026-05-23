from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():

    # Temporary fake odometry: publishes a static identity transform odom →
    # base_footprint so slam_toolbox can build a map while the robot is moved
    # manually (motors not yet connected).
    fake_odom = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='fake_odom',
        arguments=['0', '0', '0', '0', '0', '0', 'odom', 'base_footprint'],
        output='screen',
    )

    slam = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        parameters=[{'use_sim_time': False}],
    )

    return LaunchDescription([
        fake_odom,
        slam,
    ])
