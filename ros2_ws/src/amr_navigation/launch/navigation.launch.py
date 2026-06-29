"""
navigation.launch.py — AMR Warehouse autonomous navigation (ROS 2 Humble)

Brings up:
  1. Localization  — map_server + amcl  (via nav2_bringup localization_launch.py)
  2. Navigation    — controller, planner, bt_navigator, behaviors, velocity_smoother
  3. twist_mux     — joystick (cmd_vel_joy, prio 100) overrides Nav2 (cmd_vel_nav, prio 10)

Topic flow:
  controller_server  →  cmd_vel_ctrl
  velocity_smoother  subscribes cmd_vel_ctrl, publishes cmd_vel_nav
  twist_mux          merges cmd_vel_nav + cmd_vel_joy  →  cmd_vel
  serial_bridge_node subscribes cmd_vel  →  Teensy motor controller

Foxy → Humble notes (affects this launch file):
  • robot_model_type must use the full class name in nav2_params.yaml
  • smoother_server is a new lifecycle node that must be included
  • recoveries_server is now behavior_server
  • nav2_bringup's navigation_launch.py already remaps controller→cmd_vel_nav;
    we re-implement those nodes here to change velocity_smoother's OUTPUT from
    cmd_vel (Humble default) to cmd_vel_nav so twist_mux sits between Nav2 and robot.
"""

import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.descriptions import ParameterFile
from nav2_common.launch import RewrittenYaml


# Map committed inside the amr_navigation package — portable, no username hardcoding
MAP_YAML = os.path.join(get_package_share_directory('amr_navigation'), 'maps', 'warehouse_map.yaml')

def generate_launch_description():
    nav_share      = get_package_share_directory('amr_navigation')
    nav2_bringup   = get_package_share_directory('nav2_bringup')

    params_file      = os.path.join(nav_share, 'config', 'nav2_params.yaml')
    twist_mux_config = os.path.join(nav_share, 'config', 'twist_mux.yaml')

    # ── Launch arguments ───────────────────────────────────────────────────
    use_sim_time    = LaunchConfiguration('use_sim_time')
    autostart       = LaunchConfiguration('autostart')
    use_respawn     = LaunchConfiguration('use_respawn')
    log_level       = LaunchConfiguration('log_level')
    use_composition = LaunchConfiguration('use_composition')

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time', default_value='false',
        description='Use simulation clock (false = real hardware)')
    declare_autostart = DeclareLaunchArgument(
        'autostart', default_value='true',
        description='Automatically activate all lifecycle nodes on startup')
    declare_use_respawn = DeclareLaunchArgument(
        'use_respawn', default_value='false',
        description='Respawn crashed nodes automatically')
    declare_log_level = DeclareLaunchArgument(
        'log_level', default_value='info',
        description='ROS 2 logging level')
    declare_use_composition = DeclareLaunchArgument(
        'use_composition', default_value='False',
        description='Launch in composable container (not recommended for debugging)')

    # ── Params file with runtime substitutions ─────────────────────────────
    configured_params = ParameterFile(
        RewrittenYaml(
            source_file=params_file,
            root_key='',
            param_rewrites={
                'use_sim_time': use_sim_time,
                'autostart': autostart,
            },
            convert_types=True,
        ),
        allow_substs=True,
    )

    # Standard TF remappings required by nav2 nodes
    tf_remaps = [('/tf', 'tf'), ('/tf_static', 'tf_static')]

    # ── 1. Localization: map_server + amcl ────────────────────────────────
    # nav2_bringup's localization_launch.py handles the lifecycle manager for
    # [map_server, amcl] and substitutes yaml_filename into nav2_params.yaml.
    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_bringup, 'launch', 'localization_launch.py')
        ),
        launch_arguments={
            'map':         MAP_YAML,
            'use_sim_time': use_sim_time,
            'params_file':  params_file,
            'autostart':    autostart,
            'use_respawn':  use_respawn,
            'log_level':    log_level,
        }.items(),
    )

    # ── 2. Navigation nodes ────────────────────────────────────────────────
    # We launch these individually (instead of including navigation_launch.py)
    # so we can override the velocity_smoother remapping.
    #
    # Humble nav2_bringup default:  velocity_smoother → cmd_vel        (feeds robot)
    # Our remapping:                velocity_smoother → cmd_vel_nav     (feeds twist_mux)
    # twist_mux then merges cmd_vel_nav (nav2) + cmd_vel_joy (joystick) → cmd_vel

    lifecycle_nodes = [
        'controller_server',
        'smoother_server',
        'planner_server',
        'behavior_server',
        'bt_navigator',
        'waypoint_follower',
        'velocity_smoother',
    ]

    navigation_nodes = GroupAction(
        condition=IfCondition(PythonExpression(['not ', use_composition])),
        actions=[

            # controller_server publishes velocity to cmd_vel_ctrl (not cmd_vel)
            # so the velocity_smoother (not the robot) receives it first.
            Node(
                package='nav2_controller',
                executable='controller_server',
                output='screen',
                respawn=use_respawn,
                respawn_delay=2.0,
                parameters=[configured_params],
                arguments=['--ros-args', '--log-level', log_level],
                remappings=tf_remaps + [('cmd_vel', 'cmd_vel_ctrl')],
            ),

            # smoother_server (path smoother, separate from velocity_smoother)
            Node(
                package='nav2_smoother',
                executable='smoother_server',
                name='smoother_server',
                output='screen',
                respawn=use_respawn,
                respawn_delay=2.0,
                parameters=[configured_params],
                arguments=['--ros-args', '--log-level', log_level],
                remappings=tf_remaps,
            ),

            Node(
                package='nav2_planner',
                executable='planner_server',
                name='planner_server',
                output='screen',
                respawn=use_respawn,
                respawn_delay=2.0,
                parameters=[configured_params],
                arguments=['--ros-args', '--log-level', log_level],
                remappings=tf_remaps,
            ),

            # behavior_server (was recoveries_server in Foxy)
            Node(
                package='nav2_behaviors',
                executable='behavior_server',
                name='behavior_server',
                output='screen',
                respawn=use_respawn,
                respawn_delay=2.0,
                parameters=[configured_params],
                arguments=['--ros-args', '--log-level', log_level],
                remappings=tf_remaps,
            ),

            Node(
                package='nav2_bt_navigator',
                executable='bt_navigator',
                name='bt_navigator',
                output='screen',
                respawn=use_respawn,
                respawn_delay=2.0,
                parameters=[configured_params],
                arguments=['--ros-args', '--log-level', log_level],
                remappings=tf_remaps,
            ),

            Node(
                package='nav2_waypoint_follower',
                executable='waypoint_follower',
                name='waypoint_follower',
                output='screen',
                respawn=use_respawn,
                respawn_delay=2.0,
                parameters=[configured_params],
                arguments=['--ros-args', '--log-level', log_level],
                remappings=tf_remaps,
            ),

            # velocity_smoother:
            #   ('cmd_vel',          'cmd_vel_ctrl') — subscribe to controller output
            #   ('cmd_vel_smoothed', 'cmd_vel_nav')  — publish to twist_mux nav input
            # This differs from Humble's nav2_bringup default where cmd_vel_smoothed
            # is remapped to cmd_vel (directly to robot). We insert twist_mux in between.
            Node(
                package='nav2_velocity_smoother',
                executable='velocity_smoother',
                name='velocity_smoother',
                output='screen',
                respawn=use_respawn,
                respawn_delay=2.0,
                parameters=[configured_params],
                arguments=['--ros-args', '--log-level', log_level],
                remappings=tf_remaps + [
                    ('cmd_vel',          'cmd_vel_ctrl'),
                    ('cmd_vel_smoothed', 'cmd_vel_nav'),
                ],
            ),

            # Single lifecycle manager for all navigation nodes
            Node(
                package='nav2_lifecycle_manager',
                executable='lifecycle_manager',
                name='lifecycle_manager_navigation',
                output='screen',
                arguments=['--ros-args', '--log-level', log_level],
                parameters=[
                    {'use_sim_time': use_sim_time},
                    {'autostart': autostart},
                    {'node_names': lifecycle_nodes},
                ],
            ),
        ],
    )

    # ── 3. twist_mux: joystick overrides Nav2 autonomy ────────────────────
    # cmd_vel_out is the internal output topic; remapped to cmd_vel here
    # so serial_bridge_node receives the final blended velocity command.
    twist_mux = Node(
        package='twist_mux',
        executable='twist_mux',
        name='twist_mux',
        output='screen',
        parameters=[twist_mux_config],
        remappings=[('cmd_vel_out', 'cmd_vel')],
    )

    return LaunchDescription([
        declare_use_sim_time,
        declare_autostart,
        declare_use_respawn,
        declare_log_level,
        declare_use_composition,
        localization,
        navigation_nodes,
        twist_mux,
    ])
