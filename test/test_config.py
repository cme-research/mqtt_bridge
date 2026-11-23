"""Validate the shipped parameter files and the client/path helpers."""

import importlib
import pathlib

import paho.mqtt.client as mqtt
import pytest
import yaml

from mqtt_bridge.bridge import Bridge, MqttToRosBridge, RosToMqttBridge
from mqtt_bridge.mqtt_client import create_private_path_extractor, default_mqtt_client_factory
from mqtt_bridge.util import lookup_object

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / 'config'
ALL_FILES = sorted(CONFIG_DIR.rglob('*.yaml'))
# Full bridge configurations; other files (e.g. tls_params.yaml) are overlays
# layered on top of one of these.
CONFIG_FILES = [
    p for p in ALL_FILES
    if 'n_bridges' in yaml.safe_load(p.read_text())['mqtt_bridge_node']['ros__parameters']
]
OVERLAY_FILES = [p for p in ALL_FILES if p not in CONFIG_FILES]
PAIRS = {('json:dumps', 'json:loads'), ('msgpack:dumps', 'msgpack:loads'),
         ('msgpack:packb', 'msgpack:unpackb')}


def params_of(path):
    data = yaml.safe_load(path.read_text())
    (node_name, body), = data.items()
    return node_name, body['ros__parameters']


def bridges_of(params):
    return [params['bridge'][key] for key in sorted(params.get('bridge', {}))]


def test_config_files_found():
    assert CONFIG_FILES, f'no bridge configurations under {CONFIG_DIR}'


@pytest.mark.parametrize('path', OVERLAY_FILES, ids=lambda p: p.relative_to(CONFIG_DIR).as_posix())
def test_overlay_only_sets_mqtt_options(path):
    node_name, params = params_of(path)
    assert node_name == 'mqtt_bridge_node'
    assert set(params) == {'mqtt'}, f'overlay should only override mqtt.* options: {set(params)}'
    allowed = {'client', 'tls', 'account', 'userdata', 'message', 'will', 'connection'}
    assert set(params['mqtt']) <= allowed


@pytest.mark.parametrize('path', CONFIG_FILES, ids=lambda p: p.relative_to(CONFIG_DIR).as_posix())
def test_param_file_shape(path):
    node_name, params = params_of(path)
    assert node_name == 'mqtt_bridge_node', 'parameters must target the node name used by app.py'
    assert 'private_path' in params['mqtt'], 'mqtt.private_path is read unconditionally'
    bridges = bridges_of(params)
    # app.py reads bridge.bridge1 .. bridge.bridge<n_bridges>.
    assert params['n_bridges'] == len(bridges)
    assert sorted(params['bridge']) == [f'bridge{i}' for i in range(1, len(bridges) + 1)]
    for entry in bridges:
        assert len(entry) == 4, f'bridge entry must be [factory, msg_type, from, to]: {entry}'


@pytest.mark.parametrize('path', CONFIG_FILES, ids=lambda p: p.relative_to(CONFIG_DIR).as_posix())
def test_bridge_entries_resolve(path):
    _, params = params_of(path)
    for factory, msg_type, topic_from, topic_to in bridges_of(params):
        cls = lookup_object(factory)
        assert issubclass(cls, Bridge)
        try:
            msg_cls = lookup_object(msg_type)
        except ModuleNotFoundError as e:
            pytest.skip(f'message package not available in this environment: {e.name}')
        assert hasattr(msg_cls, 'get_fields_and_field_types'), f'{msg_type} is not a ROS message'
        if cls is RosToMqttBridge:
            assert topic_from.startswith('/'), f'ROS topic should be absolute: {topic_from}'
        if cls is MqttToRosBridge:
            assert topic_to.startswith('/'), f'ROS topic should be absolute: {topic_to}'


@pytest.mark.parametrize('path', CONFIG_FILES, ids=lambda p: p.relative_to(CONFIG_DIR).as_posix())
def test_serializer_pair_matches(path):
    _, params = params_of(path)
    ser = params.get('serializer', 'msgpack:dumps')
    de = params.get('deserializer', 'msgpack:loads')
    assert (ser, de) in PAIRS, f'serializer {ser} does not match deserializer {de}'
    for spec in (ser, de):
        module, name = spec.split(':')
        assert callable(getattr(importlib.import_module(module), name))


def test_private_path_extractor():
    extract = create_private_path_extractor('robots/r1')
    assert extract('~/odom') == 'robots/r1/odom'
    assert extract('~/a/b') == 'robots/r1/a/b'
    assert extract('/abs/topic') == '/abs/topic'
    assert extract('rel/topic') == 'rel/topic'


class Param:
    """Stands in for rclpy.Parameter (the factory only reads .value)."""

    def __init__(self, value):
        self.value = value


def test_client_factory_applies_account_and_will():
    client_params = {}
    if hasattr(mqtt, 'CallbackAPIVersion'):  # paho-mqtt >= 2.0
        client_params['callback_api_version'] = Param(mqtt.CallbackAPIVersion.VERSION1)
    client = default_mqtt_client_factory({
        'client': client_params,
        'account': {'username': Param('robot'), 'password': Param('secret')},
        'will': {'topic': Param('robots/r1/status'), 'payload': Param('offline')},
        'userdata': {'robot': Param('r1')},
    })
    assert isinstance(client, mqtt.Client)
    assert client._username in ('robot', b'robot')
    assert client._userdata == {'robot': 'r1'}
    assert client._will_topic in ('robots/r1/status', b'robots/r1/status')
