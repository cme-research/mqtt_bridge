#!/bin/bash

source "/robot/ros2_ws/install/setup.bash"

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

exec "$@"
