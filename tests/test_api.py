import time
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from evoforge.api.app import create_app

TOKEN = 'integration-test-private-token'
HEADERS = {'Authorization': f'Bearer {TOKEN}'}
CONFIG = {'game': 'coin', 'mode': 'ppo', 'population': 2, 'elites': 1,
          'ppo_candidates': 0, 'generations': 10000, 'ppo_episodes': 1, 'eval_episodes': 1,
          'hidden': [8, 8], 'game_config': {'horizon': 20}}


def until(client, name, state):
    deadline = time.monotonic()+20
    while time.monotonic() < deadline:
        result = client.get(f'/api/v1/experiments/{name}', headers=HEADERS).json()
        if result['status'] == state:
            return result
        assert result['status'] != 'FAILED', result
        time.sleep(.03)
    pytest.fail(f'Timeout awaiting {state}: {result}')


def test_authentication_validation_and_remote_guard(tmp_path):
    with pytest.raises(ValueError, match='requires'):
        create_app(tmp_path, token='', bind_host='0.0.0.0')
    client = TestClient(create_app(tmp_path, TOKEN))
    assert client.get('/api/v1/games').status_code == 401
    assert client.get('/api/v1/games', headers={'Authorization': 'Bearer wrong'}).status_code == 401
    assert any(game['id'] == 'coin' for game in client.get('/api/v1/games', headers=HEADERS).json())
    assert client.get('/api/v1/games/absent', headers=HEADERS).status_code == 404
    for data in ({'id': '../escape'}, {'id': 'bad', 'config': {'population': '2'}}, {'id': 'bad', 'config': {'game': 'absent'}},
                 {'id': 'bad', 'config': {'shell': 'echo nope'}}, {'id': 'bad', 'config': {'hidden': []}}):
        assert client.post('/api/v1/experiments', headers=HEADERS, json=data).status_code == 422
    with pytest.raises(WebSocketDisconnect) as rejected:
        with client.websocket_connect('/api/v1/events'):
            pass
    assert rejected.value.code == 4401
    assert '/api/v1/experiments/{experiment}/start' in client.get('/openapi.json').json()['paths']


def test_crud_events_and_reconnect_cursor(tmp_path):
    client = TestClient(create_app(tmp_path, TOKEN))
    created = client.post('/api/v1/experiments', headers=HEADERS, json={'id': 'demo', 'config': CONFIG})
    assert created.status_code == 201, created.text
    assert client.post('/api/v1/experiments', headers=HEADERS, json={'id': 'demo'}).status_code == 409
    assert client.get('/api/v1/experiments', headers=HEADERS).json()[0]['id'] == 'demo'
    assert client.put('/api/v1/experiments/demo', headers=HEADERS, json=CONFIG).status_code == 200
    assert client.post('/api/v1/experiments/demo/duplicate', headers=HEADERS, json={'destination': 'copy'}).status_code == 201
    assert client.post('/api/v1/experiments/copy/rename', headers=HEADERS, json={'destination': 'renamed'}).status_code == 200
    assert client.delete('/api/v1/experiments/renamed', headers=HEADERS).json()['archived'] == 1
    assert client.post('/api/v1/experiments/renamed/unarchive', headers=HEADERS).json()['archived'] == 0
    with client.websocket_connect('/api/v1/events', headers=HEADERS) as socket:
        batch = socket.receive_json()
        assert batch['events']
        cursor = batch['cursor']
    with client.websocket_connect(f'/api/v1/events?since={cursor}', headers=HEADERS) as socket:
        assert socket.receive_json()['events'] == []
    assert client.get('/api/v1/experiments/missing', headers=HEADERS).status_code == 404
    assert client.get('/api/v1/experiments/demo/agents', headers=HEADERS).json()['agents'] == []


def test_api_controls_real_supervisor_and_live_websocket(tmp_path):
    app = create_app(tmp_path, TOKEN)
    client = TestClient(app)
    assert client.post('/api/v1/experiments', headers=HEADERS, json={'id': 'worker', 'config': CONFIG}).status_code == 201
    assert client.post('/api/v1/experiments/worker/start', headers=HEADERS).status_code == 200
    try:
        until(client, 'worker', 'RUNNING')
        assert client.post('/api/v1/experiments/worker/start', headers=HEADERS).status_code == 409
        assert client.get('/api/v1/workers', headers=HEADERS).json()[0]['worker']['identity']
        with client.websocket_connect('/api/v1/experiments/worker/spectator', headers=HEADERS) as socket:
            batch = socket.receive_json()
            for _ in range(100):
                if batch['frames']:
                    break
                batch = socket.receive_json()
            assert batch['frames'] and 'Coin:' in batch['frames'][0]['data']['text']
            cursor = batch['cursor']
        assert client.post('/api/v1/experiments/worker/pause', headers=HEADERS).status_code == 200
        until(client, 'worker', 'PAUSED')
        with client.websocket_connect(f'/api/v1/experiments/worker/spectator?since={cursor}', headers=HEADERS) as socket:
            frames = socket.receive_json()['frames']
            assert all(frame['seq'] > cursor for frame in frames)
        assert client.post('/api/v1/experiments/worker/resume', headers=HEADERS).status_code == 200
        until(client, 'worker', 'RUNNING')
    finally:
        assert client.post('/api/v1/experiments/worker/stop', headers=HEADERS).status_code == 200
        until(client, 'worker', 'STOPPED')
