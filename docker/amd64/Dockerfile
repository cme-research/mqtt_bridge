FROM amd64/ros:rolling-ros-base-noble

LABEL version="0.1"
LABEL description="Adaptions for mqtt_bridge to run with ros-rolling"

# USE BASH
SHELL ["/bin/bash", "-c"]

RUN apt-get update && apt-get install --no-install-recommends -y \
    build-essential \
    git \
    python3-colcon-common-extensions \
    python3-colcon-mixin \
    python3-rosdep \
    python3-vcstool \
    && rm -rf /var/lib/apt/lists/*

ENV DEBIAN_FRONTEND=noninteractive
RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections

# install helpers and requirements
RUN apt-get update && apt-get -y install curl software-properties-common vim wget
RUN add-apt-repository universe
#RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg
#RUN echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null

# upgrade and install build tools (catkin)
# run all commands in one call is important

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y ros-dev-tools python3-rosdep


# workaround for missing rosdep definition (external package)
RUN apt-get update \
    && apt-get install -y python3-pip


# workaround for ros2 not running on raspi aarch64 --> use other dds layer
# make sure to add export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp to sourceing file (or bashrc)
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update \
   && apt-get install -y ros-rolling-rmw-cyclonedds-cpp


# Create local catkin workspace
ENV CATKIN_WS=/robot/ros2_ws

#### mqtt_bridge ###
RUN mkdir -p /robot/ros2_ws/src/mqtt_bridge
COPY ../.. /robot/ros2_ws/src/mqtt_bridge

# add package specific ros dependencies to workspace
RUN source /opt/ros/rolling/setup.bash \
    && cd /robot/ros2_ws/  \
    && apt-get update \
#    && rosdep init \
    && rosdep update \
    && rosdep fix-permissions \
    && rosdep install -y -r --from-paths src --ignore-src --rosdistro=rolling -y

RUN source /opt/ros/rolling/setup.bash \
    && cd /robot/ros2_ws \
    && colcon build

# just leave install space inside container
RUN cd /robot/ros2_ws/ \
    && rm -rf build \
    && rm -rf log \
    && rm -rf src

RUN rm -rf /var/lib/apt/lists/*

# Always source ros_entrypoint.sh when launching bash (e.g. when attaching to container)
RUN echo "source /ros_entrypoint.sh" >> /root/.bashrc

COPY ros_entrypoint.sh /
RUN chmod +x /ros_entrypoint.sh

ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["ros2", "launch", "mqtt_bridge", "cmexa_demo.launch.py"]
