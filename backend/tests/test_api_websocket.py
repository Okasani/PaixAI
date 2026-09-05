from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


def test_health_and_provider_manifests() -> None:
    with TestClient(app) as client:
        landing = client.get("/")
        health = client.get("/api/health")
        providers = client.get("/api/providers")
        avatars = client.get("/api/avatars")

    assert landing.status_code == 200
    assert landing.json()["primary_interface"] == "python -m app.voice.cli"
    assert health.status_code == 200
    assert health.json()["database"] == "ok"
    assert providers.status_code == 200
    assert {item["id"] for item in providers.json()} == {"mock", "local", "openai", "anthropic", "openrouter"}
    assert next(item for item in providers.json() if item["id"] == "mock")["configured"] is True
    assert next(item for item in providers.json() if item["id"] == "local")["configured"] is True
    assert avatars.status_code == 200
    assert avatars.json()[0]["id"] == "live2d"
    assert avatars.json()[0]["capabilities"]["pcm_amplitude_lipsync"] is True


def test_websocket_rejects_untrusted_browser_origin() -> None:
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect(
                "/ws/chat?session_id=browser-session",
                headers={"origin": "https://untrusted.example"},
            ):
                pass

    assert rejected.value.code == 1008


def test_mock_websocket_turn_has_ordered_envelopes_and_persists() -> None:
    session_id = "pytest-session"
    turn_id = "pytest-turn"
    conversation_id = "pytest-conversation"
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/chat?session_id={session_id}") as socket:
            ready = socket.receive_json()
            assert ready["type"] == "session.ready"
            socket.send_json(
                {
                    "type": "chat.send",
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "sequence": 1,
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {
                        "text": "Hello Paix",
                        "provider_id": "mock",
                        "model_id": "paix-mock-1",
                        "conversation_id": conversation_id,
                        "voice_enabled": False,
                        "options": {"latency_ms": 0},
                    },
                }
            )
            events: list[dict] = []
            while len(events) < 80:
                event = socket.receive_json()
                events.append(event)
                if event["type"] == "turn.state" and event["payload"].get("state") == "idle":
                    break

        messages = client.get(f"/api/conversations/{conversation_id}/messages")

    assert any(event["type"] == "text.delta" for event in events)
    assert any(event["type"] == "response.completed" for event in events)
    assert all(event["session_id"] == session_id for event in events)
    assert all(event["turn_id"] == turn_id for event in events)
    assert [event["sequence"] for event in events] == sorted(event["sequence"] for event in events)
    assert messages.status_code == 200
    assert [message["role"] for message in messages.json()] == ["user", "assistant"]
