cmake_minimum_required(VERSION 3.8)
project(amr_navigation)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY config launch maps rviz
  DESTINATION share/${PROJECT_NAME}
)

install(
  PROGRAMS
    scripts/waypoint_saver.py
    scripts/waypoint_navigator.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
