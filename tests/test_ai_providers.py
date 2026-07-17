from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path

from life_mind.ai import (
    AIConfig,
    AIGeneration,
    AnthropicClient,
    LocalAIError,
    OllamaClient,
    OpenAICompatibleClient,
    PROVIDER_PRESETS,
    ProviderHTTPError,
    credential_id,
    create_ai_client,
    endpoint_is_remote,
    endpoint_transport_allowed,
    parse_json_text,
)
from life_mind.mind import MindEngine
from life_mind.ports import ModelAdapter


def valid_payload() -> dict[str, object]:
    return {
        "reply": "嗯，我在认真听。",
        "symbol": "♪",
        "reflection": "",
        "memories": [],
        "interpretation": {
            "primary_intent": "neutral",
            "uncertainty": 0.2,
            "hypotheses": [
                {"label": "neutral", "confidence": 0.8, "evidence": "普通交流"}
            ],
        },
    }


class FakeSecretStore:
    def __init__(self, secret: str = "test-secret") -> None:
        self.secret = secret

    def get(self, provider_id: str) -> str:
        return self.secret

    def set(self, provider_id: str, secret: str) -> None:
        self.secret = secret

    def delete(self, provider_id: str) -> None:
        self.secret = ""


class RecordingOpenAI(OpenAICompatibleClient):
    def __init__(self, config: AIConfig) -> None:
        super().__init__(config, FakeSecretStore())
        self.requests: list[tuple[str, str, dict | None]] = []

    def _request(self, method: str, route: str, payload: dict | None = None) -> dict:
        self.requests.append((method, route, payload))
        if route == "/models":
            return {"data": [{"id": "test-model"}]}
        return {
            "choices": [
                {"message": {"content": json.dumps(valid_payload(), ensure_ascii=False)}}
            ]
        }


class RecordingAnthropic(AnthropicClient):
    def __init__(self, config: AIConfig) -> None:
        super().__init__(config, FakeSecretStore())
        self.requests: list[tuple[str, str, dict | None]] = []

    def _request(self, method: str, route: str, payload: dict | None = None) -> dict:
        self.requests.append((method, route, payload))
        if route == "/v1/models":
            return {"data": [{"id": "claude-test"}]}
        return {
            "content": [
                {"type": "text", "text": json.dumps(valid_payload(), ensure_ascii=False)}
            ]
        }


class AIConfigAndPresetTests(unittest.TestCase):
    def test_invalid_timeout_and_boolean_values_fall_back_safely(self) -> None:
        path = Path(__file__).with_name(f"ai-config-{uuid.uuid4().hex}.json")
        try:
            path.write_text(
                json.dumps(
                    {
                        "enabled": "false",
                        "timeout_seconds": "bad",
                        "provider": "deepseek",
                    }
                ),
                encoding="utf-8",
            )
            config = AIConfig.load(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertFalse(config.enabled)
        self.assertFalse(config.share_memory)
        self.assertEqual(config.timeout_seconds, 45.0)
        self.assertEqual(config.provider, "deepseek")

    def test_config_never_serializes_api_key(self) -> None:
        path = Path(__file__).with_name(f"ai-config-{uuid.uuid4().hex}.json")
        temporary = path.with_suffix(".tmp")
        try:
            AIConfig(provider="openrouter", api_key_env="OPENROUTER_API_KEY").save(path)
            serialized = path.read_text(encoding="utf-8")
        finally:
            path.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
        self.assertNotIn("test-secret", serialized)
        self.assertNotIn('"api_key"', serialized)

    def test_presets_cover_local_catch_all_and_direct_anthropic(self) -> None:
        protocols = {preset.protocol for preset in PROVIDER_PRESETS}
        provider_ids = {preset.provider_id for preset in PROVIDER_PRESETS}
        self.assertEqual(protocols, {"ollama", "openai", "anthropic"})
        self.assertTrue({"deepseek", "zhipu", "gemini", "qwen", "openrouter"} <= provider_ids)

    def test_remote_endpoint_detection_is_host_based(self) -> None:
        self.assertFalse(endpoint_is_remote("http://127.0.0.1:11434"))
        self.assertFalse(endpoint_is_remote("http://localhost:1234/v1"))
        self.assertTrue(endpoint_is_remote("https://api.deepseek.com"))
        self.assertNotEqual(
            credential_id("custom-openai", "https://one.example/v1"),
            credential_id("custom-openai", "https://two.example/v1"),
        )

    def test_credential_identity_preserves_case_sensitive_paths(self) -> None:
        self.assertEqual(
            credential_id("custom-openai", "HTTPS://API.EXAMPLE/v1/"),
            credential_id("custom-openai", "https://api.example/v1"),
        )
        self.assertNotEqual(
            credential_id("custom-openai", "https://api.example/TenantA/v1"),
            credential_id("custom-openai", "https://api.example/tenanta/v1"),
        )

    def test_plain_http_is_limited_to_loopback_endpoints(self) -> None:
        self.assertTrue(endpoint_transport_allowed("http://127.0.0.1:11434"))
        self.assertTrue(endpoint_transport_allowed("http://[::1]:11434"))
        self.assertFalse(endpoint_transport_allowed("http://192.168.1.20:8000/v1"))
        self.assertFalse(endpoint_transport_allowed("http://api.example/v1"))
        self.assertTrue(endpoint_transport_allowed("https://api.example/v1"))

        client = OpenAICompatibleClient(
            AIConfig(
                provider="custom-openai",
                endpoint="http://api.example/v1",
                model="test-model",
                remote_consent=True,
                consent_endpoint="http://api.example/v1",
            ),
            FakeSecretStore(),
        )
        ok, detail = client.status()
        self.assertFalse(ok)
        self.assertIn("https://", detail)

    def test_factory_clients_conform_to_model_adapter_port(self) -> None:
        clients = (
            create_ai_client(AIConfig(provider="ollama"), FakeSecretStore()),
            create_ai_client(
                AIConfig(provider="custom-openai", endpoint="http://localhost:8000/v1"),
                FakeSecretStore(),
            ),
            create_ai_client(
                AIConfig(provider="anthropic", endpoint="https://api.anthropic.com"),
                FakeSecretStore(),
            ),
        )
        self.assertIsInstance(clients[0], OllamaClient)
        self.assertTrue(all(isinstance(client, ModelAdapter) for client in clients))


class ProviderProtocolTests(unittest.TestCase):
    def test_json_parser_accepts_fence_but_rejects_surrounding_prose(self) -> None:
        payload = valid_payload()
        self.assertEqual(
            parse_json_text(f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"),
            payload,
        )
        with self.assertRaises(LocalAIError):
            parse_json_text(f"结果如下：{json.dumps(payload, ensure_ascii=False)}")

    def test_remote_generation_requires_explicit_consent(self) -> None:
        client = RecordingOpenAI(
            AIConfig(
                provider="deepseek",
                endpoint="https://api.deepseek.com",
                model="test-model",
                remote_consent=False,
                api_key_env="LIFE_MIND_TEST_MISSING_KEY",
            )
        )
        with self.assertRaisesRegex(LocalAIError, "许可"):
            client.generate([{"role": "user", "content": "你好"}], allow_reflection=False)
        self.assertEqual(client.requests, [])
        client.config.remote_consent = True
        client.config.consent_endpoint = "https://old.example/v1"
        with self.assertRaisesRegex(LocalAIError, "地址已改变"):
            client.generate([{"role": "user", "content": "你好"}], allow_reflection=False)
        ollama_cloud = OllamaClient(
            AIConfig(
                endpoint="https://ollama.example.invalid",
                model="test-model",
                provider="ollama",
            )
        )
        with self.assertRaisesRegex(LocalAIError, "许可"):
            ollama_cloud.generate(
                [{"role": "user", "content": "你好"}], allow_reflection=False
            )

    def test_openai_compatible_request_uses_portable_json_mode(self) -> None:
        client = RecordingOpenAI(
            AIConfig(
                provider="deepseek",
                endpoint="https://api.deepseek.com",
                model="test-model",
                remote_consent=True,
                consent_endpoint="https://api.deepseek.com",
                api_key_env="LIFE_MIND_TEST_MISSING_KEY",
            )
        )
        generation = client.generate(
            [{"role": "user", "content": "你好"}], allow_reflection=False
        )
        _, route, payload = client.requests[-1]
        self.assertEqual(route, "/chat/completions")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertNotIn("temperature", payload)
        self.assertEqual(client._headers()["Authorization"], "Bearer test-secret")
        self.assertEqual(generation.model, "test-model")

        class NoModelList(RecordingOpenAI):
            def models(self):
                raise ProviderHTTPError(404, "not implemented")

        ok, detail = NoModelList(client.config).status()
        self.assertTrue(ok)
        self.assertIn("首次对话", detail)

    def test_openai_adapter_retries_without_unsupported_json_mode(self) -> None:
        class FallbackClient(RecordingOpenAI):
            def _completion(self, model, messages, *, json_mode):
                if json_mode:
                    raise ProviderHTTPError(400, "response_format unsupported")
                return {
                    "choices": [
                        {"message": {"content": json.dumps(valid_payload(), ensure_ascii=False)}}
                    ]
                }

        client = FallbackClient(
            AIConfig(
                provider="custom-openai",
                endpoint="https://example.invalid/v1",
                model="test-model",
                remote_consent=True,
                consent_endpoint="https://example.invalid/v1",
            )
        )
        self.assertEqual(
            client.generate([{"role": "user", "content": "你好"}], allow_reflection=False).reply,
            "嗯，我在认真听。",
        )

    def test_anthropic_messages_api_separates_system_messages(self) -> None:
        client = RecordingAnthropic(
            AIConfig(
                provider="anthropic",
                endpoint="https://api.anthropic.com",
                model="claude-test",
                remote_consent=True,
                consent_endpoint="https://api.anthropic.com",
                api_key_env="LIFE_MIND_TEST_MISSING_KEY",
            )
        )
        generation = client.generate(
            [
                {"role": "system", "content": "人格边界"},
                {"role": "user", "content": "你好"},
            ],
            allow_reflection=False,
        )
        _, route, payload = client.requests[-1]
        self.assertEqual(route, "/v1/messages")
        self.assertIn("人格边界", payload["system"])
        self.assertTrue(all(item["role"] != "system" for item in payload["messages"]))
        self.assertEqual(client._headers()["x-api-key"], "test-secret")
        self.assertEqual(client._headers()["anthropic-version"], "2023-06-01")
        self.assertEqual(generation.model, "claude-test")


class MemoryAdmissionTests(unittest.TestCase):
    def test_model_memory_requires_direct_evidence_in_current_user_turn(self) -> None:
        self.assertFalse(
            MindEngine._ai_memory_has_direct_evidence("用户喜欢安静的音乐", "preference", "你好")
        )
        self.assertFalse(
            MindEngine._ai_memory_has_direct_evidence("用户喜欢摇滚", "preference", "我喜欢古典乐")
        )
        self.assertFalse(
            MindEngine._ai_memory_has_direct_evidence(
                "用户喜欢摇滚", "preference", "我喜欢古典音乐但不喜欢摇滚"
            )
        )
        self.assertTrue(
            MindEngine._ai_memory_has_direct_evidence(
                "用户喜欢安静的音乐", "preference", "我偏爱安静的音乐"
            )
        )

    def test_disabled_memory_sharing_removes_memory_context(self) -> None:
        class CapturingResponder:
            adapter_id = "capture"
            config = AIConfig(enabled=True, share_memory=False)

            def generate(self, messages, *, allow_reflection):
                return AIGeneration("我在听。", model="capture")

        path = Path(__file__).with_name(f"mind-provider-{uuid.uuid4().hex}.db")
        try:
            engine = MindEngine(path)
            engine.process_user_text("我喜欢安静的音乐。")
            engine.ai_responder = CapturingResponder()
            engine.process_user_text("你还好吗？")
            audit = engine.debug_snapshot()["last_ai_audit"]
            engine.close()
        finally:
            for suffix in ("", "-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)
        self.assertEqual(audit["ai_input_summary"]["memory_ids"], [])
        self.assertFalse(audit["ai_input_summary"]["memory_sharing"])

    def test_unexpected_adapter_exception_recovers_to_offline_rules(self) -> None:
        class CrashingResponder:
            adapter_id = "crash"

            def generate(self, messages, *, allow_reflection):
                raise RuntimeError("provider bug")

        path = Path(__file__).with_name(f"mind-provider-{uuid.uuid4().hex}.db")
        try:
            engine = MindEngine(path, ai_responder=CrashingResponder())
            response = engine.process_user_text("你好")
            engine.close()
        finally:
            for suffix in ("", "-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)
        self.assertFalse(response.ai_generated)
        self.assertIn("离线规则", response.ai_status)


if __name__ == "__main__":
    unittest.main()
