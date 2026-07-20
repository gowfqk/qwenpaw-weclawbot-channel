"""Protocol conversion tests that do not require a QwenPaw installation."""

import importlib
import sys
import types
import unittest
import asyncio
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def load_channel_module():
    """Install the minimal host API surface needed to import the plugin."""
    for name in list(sys.modules):
        if name == "channel" or name.startswith("qwenpaw"):
            sys.modules.pop(name)

    base = types.ModuleType("qwenpaw.app.channels.base")
    class BaseChannel:
        def __init__(self, *args, **kwargs):
            self._enqueue = None

        async def _on_process_completed(self, request, to_handle, send_meta):
            return None

    base.BaseChannel = BaseChannel
    base.ContentType = types.SimpleNamespace(TEXT="text")
    base.OnReplySent = object
    base.ProcessHandler = object
    base.TextContent = lambda **kwargs: kwargs

    sys.modules["qwenpaw"] = types.ModuleType("qwenpaw")
    sys.modules["qwenpaw.app"] = types.ModuleType("qwenpaw.app")
    sys.modules["qwenpaw.app.channels"] = types.ModuleType("qwenpaw.app.channels")
    sys.modules["qwenpaw.app.channels.base"] = base
    return importlib.import_module("channel")


class ProtocolAdapterTest(unittest.TestCase):
    def test_text_chat_converts_to_native_payload(self):
        channel = load_channel_module()

        native = channel.BridgeProtocolAdapter.native_from_bridge_chat(
            {"type": "chat", "id": "req_1", "payload": {"message": {"text": " hello "}}},
            channel_id="weclawbot",
            agent_id="qwenpaw",
        )

        self.assertEqual(native, {
            "channel_id": "weclawbot",
            "sender_id": "weclawbot:default",
            "session_id": "weclawbot:qwenpaw",
            "text": "hello",
            "meta": {
                "bridge_request_id": "req_1",
                "source": "wechat",
                "agent_id": "qwenpaw",
            },
        })

    def test_invalid_chat_with_id_has_a_correlated_error_response(self):
        channel = load_channel_module()
        message = {"type": "chat", "id": "req_2", "payload": {"message": {"text": " "}}}

        self.assertIsNone(channel.BridgeProtocolAdapter.native_from_bridge_chat(
            message, channel_id="weclawbot", agent_id="qwenpaw"
        ))
        self.assertEqual(channel.BridgeProtocolAdapter.invalid_chat_error(message), {
            "type": "error",
            "id": "req_2",
            "reason": "Only non-empty text messages are supported",
        })

    def test_outbound_responses_are_bridge_wire_messages(self):
        channel = load_channel_module()

        self.assertEqual(channel.BridgeProtocolAdapter.bridge_chat_reply("req_3", "done"), {
            "type": "chat",
            "id": "req_3",
            "text": "done",
            "final": True,
        })
        self.assertEqual(channel.BridgeProtocolAdapter.bridge_error("req_3", "failed"), {
            "type": "error",
            "id": "req_3",
            "reason": "failed",
        })

    def test_invalid_chat_is_returned_to_the_bridge(self):
        channel = load_channel_module()
        instance = channel.WeClawBotChannel(
            process=None,
            enabled=True,
            token="token",
        )
        sent = []

        async def capture(message):
            sent.append(message)

        instance._send_raw = capture
        asyncio.run(instance._handle_inbound({
            "type": "chat",
            "id": "req_4",
            "payload": {"message": {"text": ""}},
        }))

        self.assertEqual(sent, [{
            "type": "error",
            "id": "req_4",
            "reason": "Only non-empty text messages are supported",
        }])


class IdentityConfigTest(unittest.TestCase):
    """The plugin must not impose an Agent name/command on the Bridge.

    Sending hardcoded defaults ("QwenPaw"/"qwenpaw") on every connect would
    reset the panel-configured command and make it impossible to run more than
    one QwenPaw instance against the same Bridge.
    """

    def test_unset_identity_fields_stay_empty(self):
        channel = load_channel_module()
        instance = channel.WeClawBotChannel(process=None, enabled=True, token="token")

        # Left blank → empty, so the auth handshake defers to the Bridge panel.
        self.assertEqual(instance._agent_name, "")
        self.assertEqual(instance._command, "")

    def test_explicit_identity_fields_are_preserved(self):
        channel = load_channel_module()
        instance = channel.WeClawBotChannel(
            process=None,
            enabled=True,
            token="token",
            agent_name="QwenPaw A",
            command="qa",
        )

        self.assertEqual(instance._agent_name, "QwenPaw A")
        self.assertEqual(instance._command, "qa")


if __name__ == "__main__":
    unittest.main()
