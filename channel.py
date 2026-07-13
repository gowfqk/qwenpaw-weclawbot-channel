# -*- coding: utf-8 -*-
"""WeClawBot-Bridge WS Remote Agent channel.

Connects QwenPaw to WeChat through the WeClawBot-Bridge WebSocket protocol.
Runs a persistent WS client that authenticates, receives chat messages,
dispatches them to QwenPaw's agent pipeline, and sends replies back.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

from qwenpaw.app.channels.base import (
    BaseChannel,
    ContentType,
    OnReplySent,
    ProcessHandler,
    TextContent,
)

logger = logging.getLogger(__name__)

DEFAULT_BRIDGE_URL = "wss://<your-bridge-url>/ws/agent"
DEFAULT_AGENT_ID = "qwenpaw"
RECONNECT_INITIAL = 3.0
RECONNECT_MAX = 60.0
PING_INTERVAL = 25.0


class WeClawBotChannel(BaseChannel):
    """WebSocket channel adapter for WeClawBot-Bridge.

    Configuration fields (set via QwenPaw console or config):
      - token: Bridge WS Remote Agent token (required)
      - bridge_url: WebSocket URL (default: DEFAULT_BRIDGE_URL)
      - agent_id: Bridge Agent ID (default: "qwenpaw")
      - agent_name: display name (default: "QwenPaw")
      - command: command alias (default: "qwenpaw")

    Environment variables (override config for the default instance):
      WECLAWBOT_TOKEN
      WECLAWBOT_BRIDGE_URL
      WECLAWBOT_AGENT_ID
    """

    channel = "weclawbot"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        token: str = "",
        bridge_url: str = "",
        agent_id: str = "",
        agent_name: str = "",
        command: str = "",
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        no_text_debounce: bool = True,
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list] = None,
        deny_message: str = "",
        require_mention: bool = False,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            no_text_debounce=no_text_debounce,
            filter_thinking=filter_thinking,
            dm_policy=dm_policy,
            group_policy=group_policy,
            allow_from=allow_from,
            deny_message=deny_message,
            require_mention=require_mention,
        )
        self.enabled = enabled

        # Resolve config with env overrides.
        self._token = os.getenv("WECLAWBOT_TOKEN", "").strip() or token
        self._bridge_url = (
            os.getenv("WECLAWBOT_BRIDGE_URL", "").strip()
            or bridge_url
            or DEFAULT_BRIDGE_URL
        )
        self._agent_id = (
            os.getenv("WECLAWBOT_AGENT_ID", "").strip()
            or agent_id
            or DEFAULT_AGENT_ID
        )
        self._agent_name = agent_name or "QwenPaw"
        self._command = command or "qwenpaw"

        # Runtime state.
        self._ws: Any = None
        self._running = False
        self._listener_task: Optional[asyncio.Task] = None
        self._outbound_lock = asyncio.Lock()
        # Map chat_id → Bridge request id for reply routing.
        self._request_ids: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Factory (required by BaseChannel)
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Any,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        no_text_debounce: bool = True,
        filter_thinking: bool = False,
    ) -> "WeClawBotChannel":
        return cls(
            process=process,
            enabled=getattr(config, "enabled", False),
            token=getattr(config, "token", "") or "",
            bridge_url=getattr(config, "bridge_url", "") or "",
            agent_id=getattr(config, "agent_id", "") or "",
            agent_name=getattr(config, "agent_name", "") or "",
            command=getattr(config, "command", "") or "",
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            no_text_debounce=no_text_debounce,
            filter_thinking=filter_thinking,
            dm_policy=getattr(config, "dm_policy", "") or "open",
            group_policy=getattr(config, "group_policy", "") or "open",
            allow_from=getattr(config, "allow_from", None) or [],
            deny_message=getattr(config, "deny_message", "") or "",
            require_mention=getattr(config, "require_mention", False),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to the Bridge and begin the message loop."""
        if not self.enabled:
            return
        if not self._token:
            logger.error("WeClawBot: WECLAWBOT_TOKEN is required")
            return
        self._running = True
        self._listener_task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        """Gracefully disconnect."""
        self._running = False
        task = self._listener_task
        self._listener_task = None
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close(code=1000, reason="QwenPaw shutdown")
            except Exception:
                pass
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # WebSocket listen loop
    # ------------------------------------------------------------------

    async def _listen_loop(self) -> None:
        import websockets
        from websockets.exceptions import ConnectionClosed

        backoff = RECONNECT_INITIAL
        while self._running:
            try:
                async with websockets.connect(
                    self._bridge_url,
                    ping_interval=PING_INTERVAL,
                    ping_timeout=20,
                    close_timeout=10,
                    max_size=256 * 1024,
                ) as ws:
                    self._ws = ws
                    await self._send_raw({
                        "type": "auth",
                        "token": self._token,
                        "agentId": self._agent_id,
                        "name": self._agent_name,
                        "command": self._command,
                        "description": "QwenPaw Channel Plugin",
                    })
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    auth = self._decode(raw)
                    if auth.get("type") != "auth_ok":
                        reason = auth.get("reason", "unknown")
                        logger.error(
                            "WeClawBot: authentication rejected — %s", reason
                        )
                        return  # Do not retry on auth failure.
                    logger.info(
                        "WeClawBot: authenticated as agent %s", self._agent_id
                    )
                    backoff = RECONNECT_INITIAL

                    async for raw in ws:
                        await self._handle_inbound(self._decode(raw))
            except asyncio.CancelledError:
                break
            except ConnectionClosed as exc:
                if self._running:
                    logger.warning(
                        "WeClawBot: WS closed (%s); reconnecting in %.0fs",
                        exc, backoff,
                    )
            except Exception as exc:
                if self._running:
                    logger.warning(
                        "WeClawBot: connection error (%s); reconnecting in %.0fs",
                        exc, backoff,
                    )
            finally:
                self._ws = None
            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX)

    # ------------------------------------------------------------------
    # Inbound message handling
    # ------------------------------------------------------------------

    @staticmethod
    def _decode(raw: Any) -> Dict[str, Any]:
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    async def _handle_inbound(self, msg: Dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "ping":
            await self._send_raw({"type": "pong"})
            return
        if kind != "chat":
            if kind == "error":
                logger.warning(
                    "WeClawBot: Bridge error: %s", msg.get("reason", "unknown")
                )
            return

        request_id = msg.get("id")
        payload = msg.get("payload")
        if not isinstance(request_id, str) or not isinstance(payload, dict):
            return

        body = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            await self._reply_error(request_id, "Only non-empty text messages are supported")
            return

        # Store request id so send() can find it for the reply.
        chat_id = f"default:{self._agent_id}"
        self._request_ids[chat_id] = request_id

        # Build and dispatch an agent request.
        content_parts = [
            TextContent(type=ContentType.TEXT, text=text.strip()),
        ]
        meta = {
            "bridge_request_id": request_id,
            "source": "wechat",
            "agent_id": self._agent_id,
        }
        request = self.build_agent_request_from_user_content(
            channel_id=self.channel,
            sender_id="weclawbot:default",
            session_id=chat_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        setattr(request, "channel_meta", meta)

        await self.process.handle_message(request)

    # ------------------------------------------------------------------
    # Outbound: send replies back to Bridge
    # ------------------------------------------------------------------

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a text reply back through the Bridge WebSocket."""
        if not self.enabled:
            return
        request_id = (meta or {}).get("bridge_request_id") or self._request_ids.pop(str(to_handle), None)
        if not request_id:
            logger.warning("WeClawBot: no Bridge request id for reply to %s", to_handle)
            return
        try:
            await self._send_raw({
                "type": "chat",
                "id": request_id,
                "text": text,
            })
        except Exception:
            logger.exception("WeClawBot: failed to send reply for %s", request_id)

    async def send_media(self, to_handle: str, part: Any, meta: Optional[Dict[str, Any]] = None) -> None:
        """Media is not supported; drop silently."""
        pass

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        """Build AgentRequest from native dict (used for tests / direct injection)."""
        payload = native_payload if isinstance(native_payload, dict) else {}
        text = payload.get("text") or ""
        content_parts = [TextContent(type=ContentType.TEXT, text=text)]
        return self.build_agent_request_from_user_content(
            channel_id=self.channel,
            sender_id=payload.get("sender_id", "weclawbot:default"),
            session_id=payload.get("session_id", f"default:{self._agent_id}"),
            content_parts=content_parts,
            channel_meta=payload.get("meta", {}),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _send_raw(self, message: Dict[str, Any]) -> None:
        ws = self._ws
        if ws is None:
            raise RuntimeError("WeClawBot WebSocket is not connected")
        async with self._outbound_lock:
            await ws.send(json.dumps(message, ensure_ascii=False))

    async def _reply_error(self, request_id: str, reason: str) -> None:
        try:
            await self._send_raw({"type": "error", "id": request_id, "reason": reason})
        except Exception:
            logger.debug("WeClawBot: failed to return error to Bridge", exc_info=True)

    async def health_check(self) -> Dict[str, Any]:
        connected = self._ws is not None and hasattr(self._ws, 'state') and getattr(self._ws, 'state', None) == 1
        return {
            "channel": self.channel,
            "status": "healthy" if connected else "offline",
            "detail": (
                f"Connected to {self._bridge_url} as {self._agent_id}"
                if connected
                else "WebSocket not connected"
            ),
        }
