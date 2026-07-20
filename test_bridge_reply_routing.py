"""Standalone reply-routing regression check; runs without QwenPaw installed."""
import asyncio
import sys
import types

# The plugin imports QwenPaw framework types. Stub their minimal surface so this
# transport-level test stays runnable outside a full QwenPaw installation.
base = types.ModuleType("qwenpaw.app.channels.base")
base.BaseChannel = object
base.ContentType = types.SimpleNamespace(TEXT="text")
base.OnReplySent = object
base.ProcessHandler = object
base.TextContent = object
sys.modules.setdefault("qwenpaw", types.ModuleType("qwenpaw"))
sys.modules.setdefault("qwenpaw.app", types.ModuleType("qwenpaw.app"))
sys.modules.setdefault("qwenpaw.app.channels", types.ModuleType("qwenpaw.app.channels"))
sys.modules["qwenpaw.app.channels.base"] = base

from channel import BridgeMessageBuilder, WeClawBotChannel  # noqa: E402


async def main() -> None:
    channel = object.__new__(WeClawBotChannel)
    channel.enabled = True
    sent = []

    async def capture(message):
        sent.append(message)

    channel._send_raw = capture
    # The inbound native payload carries the Bridge request ID in channel_meta.
    # A final response must keep that ID; no shared per-chat mapping is used.
    await channel.send(
        "weclawbot:default",
        "最终回答",
        meta={"bridge_request_id": "req-1"},
    )

    assert sent == [BridgeMessageBuilder.chat_reply("req-1", "最终回答")]


if __name__ == "__main__":
    asyncio.run(main())
    print("QwenPaw Bridge reply-routing check passed")
