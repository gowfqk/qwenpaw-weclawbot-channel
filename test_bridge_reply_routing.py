"""Standalone regression checks; run inside the QwenPaw runtime image."""
import asyncio
import sys
import types

# The plugin imports QwenPaw framework types. Stub their minimal surface so this
# routing regression test remains runnable without the full application.
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
    channel._request_ids = {"weclawbot:default": "req-1"}
    sent = []

    async def capture(message):
        sent.append(message)

    channel._send_raw = capture
    await channel.send("weclawbot:default", "工具中间状态")
    await channel.send("weclawbot:default", "最终回答")

    # Mapping must survive any filtered intermediate output until the final
    # delivery lifecycle clears it; no pop-on-first-send regression.
    assert channel._request_ids["weclawbot:default"] == "req-1"
    assert sent == [
        BridgeMessageBuilder.chat_reply("req-1", "工具中间状态"),
        BridgeMessageBuilder.chat_reply("req-1", "最终回答"),
    ]


if __name__ == "__main__":
    asyncio.run(main())
    print("QwenPaw Bridge reply-routing check passed")
