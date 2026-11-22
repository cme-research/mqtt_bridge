"""Behaviour tests for the ROS <-> MQTT bridges (no broker needed).

A fake MQTT client is injected in place of paho's client; bridges run against
a real rclpy node, so message conversion goes through rosbridge exactly as in
production.
"""

import json

import inject
import msgpack
import paho.mqtt.client as mqtt
import pytest
import rclpy
from geometry_msgs.msg import TwistStamped
from nav_msgs.msg import Odometry
from std_msgs.msg import String

from mqtt_bridge.bridge import create_bridge, MqttToRosBridge, RosToMqttBridge
from mqtt_bridge.mqtt_client import create_private_path_extractor

PRIVATE_PATH = 'cmeresearch/cmexa-test'


class FakeMqttClient:
    """Records what the bridges do with the MQTT client."""

    def __init__(self):
        self.published = []
        self.subscribed = []
        self.callbacks = {}

    def publish(self, topic, payload):
        self.published.append((topic, payload))

    def subscribe(self, topic):
        self.subscribed.append(topic)

    def message_callback_add(self, topic, callback):
        self.callbacks[topic] = callback


class FakeMqttMessage:

    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload


class CapturingPublisher:

    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


SERIALIZERS = {
    'json': (json.dumps, json.loads),
    'msgpack': (msgpack.packb, msgpack.unpackb),
}


@pytest.fixture(scope='module')
def ros_node():
    rclpy.init()
    node = rclpy.create_node('mqtt_bridge_test')
    yield node
    node.destroy_node()
    rclpy.shutdown()


@pytest.fixture(params=sorted(SERIALIZERS))
def codec(request):
    return request.param


@pytest.fixture
def client(codec):
    fake = FakeMqttClient()
    serialize, deserialize = SERIALIZERS[codec]

    def config(binder):
        binder.bind(mqtt.Client, fake)
        binder.bind('serializer', serialize)
        binder.bind('deserializer', deserialize)
        binder.bind('mqtt_private_path_extractor', create_private_path_extractor(PRIVATE_PATH))

    inject.clear_and_configure(config)
    yield fake
    inject.clear()


def decode(codec, payload):
    _, deserialize = SERIALIZERS[codec]
    return deserialize(payload, raw=False) if codec == 'msgpack' else deserialize(payload)


def encode(codec, data):
    serialize, _ = SERIALIZERS[codec]
    return serialize(data)


def twist(vx, wz):
    msg = TwistStamped()
    msg.header.frame_id = 'base_link'
    msg.twist.linear.x = vx
    msg.twist.angular.z = wz
    return msg


# --- ROS -> MQTT -------------------------------------------------------------

def test_ros_to_mqtt_publishes_on_private_path(ros_node, client, codec):
    bridge = create_bridge(
        'mqtt_bridge.bridge:RosToMqttBridge', 'geometry_msgs.msg:TwistStamped',
        '/cmd_vel', '~/base/cmd_vel', ros_node=ros_node)
    assert isinstance(bridge, RosToMqttBridge)

    bridge._callback_ros(twist(0.5, -0.25))

    assert len(client.published) == 1
    topic, payload = client.published[0]
    assert topic == f'{PRIVATE_PATH}/base/cmd_vel'
    data = decode(codec, payload)
    assert data['twist']['linear']['x'] == pytest.approx(0.5)
    assert data['twist']['angular']['z'] == pytest.approx(-0.25)
    assert data['header']['frame_id'] == 'base_link'


def test_ros_to_mqtt_absolute_topic_is_kept(ros_node, client):
    bridge = create_bridge(
        'mqtt_bridge.bridge:RosToMqttBridge', 'std_msgs.msg:String',
        '/chatter', 'plain/topic', ros_node=ros_node)
    bridge._callback_ros(String(data='hi'))
    assert client.published[0][0] == 'plain/topic'


def test_ros_to_mqtt_frequency_limit(ros_node, client):
    bridge = create_bridge(
        'mqtt_bridge.bridge:RosToMqttBridge', 'std_msgs.msg:String',
        '/chatter', '~/chatter', frequency=0.01, ros_node=ros_node)  # at most every 100 s
    for i in range(5):
        bridge._callback_ros(String(data=str(i)))
    # The bridge starts its interval at construction, so nothing is due yet.
    assert len(client.published) == 0


def test_ros_to_mqtt_without_frequency_forwards_everything(ros_node, client):
    bridge = create_bridge(
        'mqtt_bridge.bridge:RosToMqttBridge', 'std_msgs.msg:String',
        '/chatter', '~/chatter', ros_node=ros_node)
    for i in range(5):
        bridge._callback_ros(String(data=str(i)))
    assert [decode_any(p)['data'] for _, p in client.published] == ['0', '1', '2', '3', '4']


def decode_any(payload):
    if isinstance(payload, (bytes, bytearray)):
        return msgpack.unpackb(payload, raw=False)
    return json.loads(payload)


def test_ros_to_mqtt_odometry_with_covariance_serializes(ros_node, client, codec):
    """nav_msgs/Odometry carries float64[36] covariance arrays (regression)."""
    bridge = create_bridge(
        'mqtt_bridge.bridge:RosToMqttBridge', 'nav_msgs.msg:Odometry',
        '/odom', '~/odom', ros_node=ros_node)
    odom = Odometry()
    odom.pose.pose.position.x = 1.5
    odom.pose.covariance[0] = 0.01
    odom.twist.covariance[35] = 0.2
    bridge._callback_ros(odom)

    assert len(client.published) == 1
    data = decode(codec, client.published[0][1])
    assert data['pose']['pose']['position']['x'] == pytest.approx(1.5)
    assert len(data['pose']['covariance']) == 36
    assert data['pose']['covariance'][0] == pytest.approx(0.01)
    assert data['twist']['covariance'][35] == pytest.approx(0.2)


def test_ros_to_mqtt_serializer_error_does_not_raise(ros_node, client):
    """A failing serializer must be logged, not kill the subscription callback."""
    bridge = create_bridge(
        'mqtt_bridge.bridge:RosToMqttBridge', 'std_msgs.msg:String',
        '/chatter', '~/chatter', ros_node=ros_node)

    def broken(_):
        raise TypeError('not serializable')

    bridge._serialize = broken
    bridge._callback_ros(String(data='x'))  # must not raise
    assert client.published == []


# --- MQTT -> ROS -------------------------------------------------------------

def make_mqtt_to_ros(ros_node, msg_type='geometry_msgs.msg:TwistStamped', **kwargs):
    bridge = create_bridge(
        'mqtt_bridge.bridge:MqttToRosBridge', msg_type,
        '~/mqtt/cmd_vel', '/mqtt/cmd_vel', ros_node=ros_node, **kwargs)
    assert isinstance(bridge, MqttToRosBridge)
    bridge._publisher = CapturingPublisher()
    return bridge


def test_mqtt_to_ros_subscribes_private_topic(ros_node, client):
    make_mqtt_to_ros(ros_node)
    expected = f'{PRIVATE_PATH}/mqtt/cmd_vel'
    assert client.subscribed == [expected]
    assert expected in client.callbacks


def test_mqtt_to_ros_publishes_ros_message(ros_node, client, codec):
    bridge = make_mqtt_to_ros(ros_node)
    payload = encode(codec, {
        'header': {'frame_id': 'base_link'},
        'twist': {'linear': {'x': 0.3}, 'angular': {'z': 1.2}},
    })
    client.callbacks[f'{PRIVATE_PATH}/mqtt/cmd_vel'](
        client, {}, FakeMqttMessage(f'{PRIVATE_PATH}/mqtt/cmd_vel', payload))

    assert len(bridge._publisher.messages) == 1
    msg = bridge._publisher.messages[0]
    assert isinstance(msg, TwistStamped)
    assert msg.twist.linear.x == pytest.approx(0.3)
    assert msg.twist.angular.z == pytest.approx(1.2)
    assert msg.header.frame_id == 'base_link'


def test_mqtt_to_ros_bad_payload_is_dropped(ros_node, client, codec):
    bridge = make_mqtt_to_ros(ros_node)
    bad = b'\xff\x00 not a valid payload' if codec == 'json' else b'\xc1'
    bridge._callback_mqtt(client, {}, FakeMqttMessage('t', bad))  # must not raise
    wrong_field = encode(codec, {'twist': {'linear': {'x': 'fast'}}})
    bridge._callback_mqtt(client, {}, FakeMqttMessage('t', wrong_field))
    assert bridge._publisher.messages == []


def test_mqtt_to_ros_frequency_limit(ros_node, client, codec):
    bridge = make_mqtt_to_ros(ros_node, frequency=0.01)
    payload = encode(codec, {'twist': {'linear': {'x': 1.0}}})
    for _ in range(3):
        bridge._callback_mqtt(client, {}, FakeMqttMessage('t', payload))
    assert bridge._publisher.messages == []


def test_round_trip_ros_mqtt_ros(ros_node, client):
    """A message bridged out and back in arrives unchanged."""
    out = create_bridge(
        'mqtt_bridge.bridge:RosToMqttBridge', 'geometry_msgs.msg:TwistStamped',
        '/cmd_vel', '~/mqtt/cmd_vel', ros_node=ros_node)
    back = make_mqtt_to_ros(ros_node)
    original = twist(-0.7, 0.4)

    out._callback_ros(original)
    topic, payload = client.published[0]
    client.callbacks[topic](client, {}, FakeMqttMessage(topic, payload))

    assert back._publisher.messages[0] == original


def test_create_bridge_rejects_non_bridge_factory(ros_node, client):
    with pytest.raises(ValueError):
        create_bridge('json:JSONDecoder', 'std_msgs.msg:String', 'a', 'b', ros_node=ros_node)
