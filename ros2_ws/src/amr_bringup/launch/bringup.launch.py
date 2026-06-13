import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.substitutions import Command
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    amr_description_share = get_package_share_directory('amr_description')

    xacro_file  = os.path.join(amr_description_share, 'urdf', 'amr_robot.urdf.xacro')
    rviz_config = os.path.join(amr_description_share, 'rviz', 'display.rviz')

    robot_description = ParameterValue(Command(['xacro ', xacro_file]), value_type=str)

    # ── Robot State Publisher ───────────────────────────────────────────────
    # Reads the URDF, publishes /robot_description, and broadcasts all fixed
    # TF transforms declared in the URDF (base_footprint → base_link →
    # laser_frame, camera_link, lift_link, wheel links, caster links).
    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_description}],
    )

    # ── Joint State Publisher GUI ───────────────────────────────────────────
    # Provides sliders for all non-fixed joints (drive wheels, lift_joint).
    # Publishes /joint_states so robot_state_publisher can broadcast their TF.
    joint_state_publisher_gui = Node(
        package='joint_state_publisher_gui',
        executable='joint_state_publisher_gui',
        output='screen',
    )

    # ── Serial Bridge (Teensy 4.1 ↔ ROS 2) ────────────────────────────────
    # Receives wheel RPM + IMU heading over USB-serial and publishes /odom
    # and the odom → base_footprint TF.  Kinematics must match the URDF.
    serial_bridge = Node(
        package='amr_hardware',
        executable='serial_bridge_node',
        name='serial_bridge_node',
        output='screen',
        parameters=[{
            'wheel_radius': 0.0625,
            'wheel_base':   0.65,
        }],
    )

    # ── SLLIDAR C1 ──────────────────────────────────────────────────────────
    # frame_id must match the URDF link name 'laser' so /scan messages
    # land in the correct TF frame without a separate static_transform_publisher.
    sllidar = Node(
        package='sllidar_ros2',
        executable='sllidar_node',
        name='sllidar_node',
        output='screen',
        parameters=[{
            'channel_type':     'serial',
            'serial_port':      '/dev/ttyUSB0',
            'serial_baudrate':  460800,
            'frame_id':         'laser',
            'inverted':         False,
            'angle_compensate': True,
            'scan_mode':        'Standard',
        }],
    )

    # ── RViz2 ───────────────────────────────────────────────────────────────
    rviz2 = Node(
        package='rviz2',
        executable='rviz2',
        output='screen',
        arguments=['-d', rviz_config],
    )

    return LaunchDescription([
        robot_state_publisher,
        joint_state_publisher_gui,
        serial_bridge,
        sllidar,
        rviz2,
    ])
