from launch import LaunchDescription
from launch_ros.actions import Node
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, RegisterEventHandler, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.substitutions import Command, FindExecutable, PathJoinSubstitution, LaunchConfiguration
from ament_index_python.packages import get_package_share_directory

from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
import launch_ros.actions
import launch
import os

def generate_launch_description():
    # Declare arguments
    declared_arguments = []
    declared_arguments.append(
        DeclareLaunchArgument(
            "mqtt_bridge_config",
            default_value=[
                launch.substitutions.TextSubstitution(text=os.path.join(
                    get_package_share_directory('mqtt_bridge'), 'config/', '')),
                'mqtt_bridge_params', launch.substitutions.TextSubstitution(text='.yaml')],
            description="Create filepath to config file",
        )
    )
    mqtt_bridge_config = LaunchConfiguration("mqtt_bridge_config")

    mqtt_bridge_node = Node(
        package="mqtt_bridge",
        executable="mqtt_bridge_node",
        name="mqtt_bridge_node",
        parameters=[mqtt_bridge_config],
        output="both",
    )

    nodes = [mqtt_bridge_node]

    return LaunchDescription(declared_arguments + nodes)