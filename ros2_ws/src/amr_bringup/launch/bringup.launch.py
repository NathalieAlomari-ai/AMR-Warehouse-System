import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.substitutions import Command
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    amr_description_share = get_package_share_directory('amr_description')
    amr_navigation_share  = get_package_share_directory('amr_navigation')

    xacro_file = os.path.join(amr_description_share, 'urdf', 'amr_robot.urdf.xacro')

    robot_description = ParameterValue(Command(['xacro ', xacro_file]), value_type=str)

    # ── Robot State Publisher ───────────────────────────────────────────────
    # Reads the URDF, publishes /robot_description, and broadcasts all fixed
    # TF transforms declared in the URDF (base_footprint → base_link →
    # laser, camera_link, lift_link, wheel links, caster links).
    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_description}],
    )

    # ── Serial Bridge (Teensy 4.1 ↔ ROS 2) ────────────────────────────────
    # Publishes two independent sensor streams for the EKF:
    #   /wheel/odometry  (nav_msgs/Odometry) — encoder-only differential-drive
    #   /imu/data        (sensor_msgs/Imu)   — BNO055 heading in IMUPLUS mode
    #
    # publish_tf is FALSE: the EKF node (ekf_node, below) owns the
    # odom → base_footprint transform.  Running two nodes that both broadcast
    # the same TF edge causes a conflict that corrupts SLAM and Nav2.
    #
    # Kinematics must match the URDF.  Do NOT run this node separately or two
    # processes will fight over the serial port.
    serial_bridge = Node(
        package='amr_hardware',
        executable='serial_bridge_node',
        name='serial_bridge_node',
        output='screen',
        parameters=[{
            'port':              '/dev/serial/by-id/usb-Teensyduino_USB_Serial_16042450-if00',
            'baudrate':          115200,
            'wheel_radius':      0.0625,
            'wheel_base':        0.65,
            'odom_frame':        'odom',
            'base_frame':        'base_footprint',
            'ticks_per_rev':     2700,
            'publish_tf':        True,    # serial_bridge owns odom → base_footprint TF
            'flip_drive_direction': True, # LiDAR is physical front; motors are at back
        }],
    )

    # ── EKF Node (robot_localization) ──────────────────────────────────────
    # Fuses /wheel/odometry (linear velocity) and /imu/data (yaw + yaw rate)
    # into a smooth, consistent /odom estimate and broadcasts the
    # odom → base_footprint TF that SLAM and Nav2 depend on.
    #
    # Configuration: amr_navigation/config/ekf.yaml
    #   odom0  /wheel/odometry  → trust vx only (encoder yaw ignored: backlash)
    #   imu0   /imu/data        → trust yaw + vyaw (BNO055 IMUPLUS gyro)
    #   imu0_relative: true     → heading zeroed at boot (no magnetometer)
    #
    # Must start before SLAM / Nav2 so the TF tree is complete on their startup.
    ekf_node = Node(
        package='robot_localization',
        executable='ekf_node',
        name='ekf_node',
        output='screen',
        parameters=[os.path.join(amr_navigation_share, 'config', 'ekf.yaml'),
                    {'publish_tf': False}],   # serial_bridge owns TF; EKF publishes /odom only
        remappings=[
            # ekf_node's default output topic is odometry/filtered.
            # Remap to /odom so SLAM toolbox and Nav2 receive the fused estimate
            # on the topic they are already configured to consume.
            ('odometry/filtered', '/odom'),
        ],
    )

    # ── Joint State Publisher ───────────────────────────────────────────────
    # Publishes zero positions for the continuous wheel joints so that
    # robot_state_publisher can broadcast their TF frames without warnings.
    # On real hardware the actual wheel angles are not needed for SLAM or Nav2
    # (only the odom pose from EKF matters); this keeps the TF tree complete.
    joint_state_publisher = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher',
        output='screen',
    )

    # ── SLLIDAR C1 ──────────────────────────────────────────────────────────
    # frame_id must match the URDF link name 'laser' so /scan messages
    # land in the correct TF frame without a separate static_transform_publisher.
    # Raw scan is published on /scan_raw; the box filter below republishes the
    # cleaned scan on /scan (which AMCL and both costmaps consume).
    sllidar = Node(
        package='sllidar_ros2',
        executable='sllidar_node',
        name='sllidar_node',
        output='screen',
        parameters=[{
            'channel_type':     'serial',
            'serial_port':      '/dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_0e2cebbea9d5ef1182e96e4b49d2c684-if00-port0',
            'serial_baudrate':  460800,
            'frame_id':         'laser',
            'inverted':         False,
            'angle_compensate': True,
            'scan_mode':        'Standard',
        }],
        remappings=[('scan', 'scan_raw')],
    )

    # ── Laser box filter ────────────────────────────────────────────────────
    # Drops returns inside the chassis footprint (the 4 scissor-lift pillars)
    # so they don't corrupt AMCL scan-matching or appear as costmap obstacles.
    # /scan_raw (raw lidar) → /scan (filtered, consumed downstream).
    laser_filter = Node(
        package='laser_filters',
        executable='scan_to_scan_filter_chain',
        name='scan_to_scan_filter_chain',
        output='screen',
        parameters=[os.path.join(amr_navigation_share, 'config', 'laser_filter.yaml')],
        remappings=[('scan', 'scan_raw'), ('scan_filtered', 'scan')],
    )

    return LaunchDescription([
        robot_state_publisher,
        joint_state_publisher,
        serial_bridge,
        ekf_node,       # must come after serial_bridge; starts TF before SLAM/Nav2
        sllidar,
        laser_filter,   # sits between the lidar and everything that reads /scan
    ])
