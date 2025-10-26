# ros2 raspi5 cmexa Dockerfile

docker run -it \
  --restart=always \
  --name cmexa-mqtt \
  --network="host" \
  --restart=always \
  --ipc=host \
  cmeresearch/cmexa-mqtt:1.0

