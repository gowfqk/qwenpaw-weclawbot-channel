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


# ------------------------------------------------------------------
# Bridge Protocol Message Builder
# ------------------------------------------------------------------
#
# Inspired by AgentScope Runtime's ResponseBuilder → MessageBuilder →
# ContentBuilder pattern.  Encapsulates Bridge ws-remote wire format
# so channel logic never touches raw dicts directly.
#

class BridgeMessageBuilder:
    """Fluent builder for Bridge ws-remote protocol messages.

    Usage::

        # Auth
        msg = BridgeMessageBuilder.auth(token="...", agentId="h", ...)

        # Reply
        msg = BridgeMessageBuilder.chat_reply(request_id="...", text="Hello")

        # Error
        msg = BridgeMessageBuilder.error(request_id="...", reason="...")

        # Heartbeat
        msg = BridgeMessageBuilder.pong()
    """

    @staticmethod
    def auth(
        token: str,
        agent_id: str,
        name: str = "",
        command: str = "",
        description: str = "",
    ) -> Dict[str, Any]:
        return {
            "type": "auth",
            "token": token,
            "agentId": agent_id,
            "name": name,
            "command": command,
            "description": description,
        }

    @staticmethod
    def chat_reply(request_id: str, text: str, final: bool = True) -> Dict[str, Any]:
        return {"type": "chat", "id": request_id, "text": text, "final": final}

    @staticmethod
    def error(request_id: str, reason: str) -> Dict[str, Any]:
        return {"type": "error", "id": request_id, "reason": reason}

    @staticmethod
    def pong() -> Dict[str, Any]:
        return {"type": "pong"}


# ------------------------------------------------------------------
# Protocol Adapter
# ------------------------------------------------------------------
#
# Separates Bridge wire format from QwenPaw's internal representation.
# Pattern from AgentScope Runtime's ProtocolAdapter base class:
# _convert_request() + _convert_response().
#

class BridgeProtocolAdapter:
    """Convert between Bridge ws-remote wire format and QwenPaw native format.

    This is a thin translation layer — no WebSocket or I/O logic lives here.
    The channel class owns the connection lifecycle; the adapter owns the
    message shape.
    """

    @staticmethod
    def native_from_bridge_chat(
        bridge_msg: Dict[str, Any],
        *,
        channel_id: str,
        agent_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Convert a Bridge ``chat`` message into a QwenPaw native payload dict.

        Returns ``None`` when the message should be dropped (non-text, no body).
        """
        request_id = bridge_msg.get("id")
        payload = bridge_msg.get("payload")
        if not isinstance(request_id, str) or not isinstance(payload, dict):
            return None

        body = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            return None

        to_handle = f"weclawbot:default"
        return {
            "channel_id": channel_id,
            "sender_id": to_handle,
            "session_id": f"weclawbot:{agent_id}",
            "text": text.strip(),
            "meta": {
                "bridge_request_id": request_id,
                "source": "wechat",
                "agent_id": agent_id,
            },
        }

    @staticmethod
    def invalid_chat_error(bridge_msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Build a protocol error for a malformed or unsupported chat request.

        The Bridge keeps a pending request for every inbound ``chat`` message,
        so a request with an ID must always receive either a chat reply or an
        error reply.  Messages without an ID cannot be correlated safely.
        """
        request_id = bridge_msg.get("id")
        if not isinstance(request_id, str) or not request_id:
            return None

        payload = bridge_msg.get("payload")
        if not isinstance(payload, dict):
            reason = "Invalid chat payload"
        else:
            message = payload.get("message")
            text = message.get("text") if isinstance(message, dict) else None
            reason = (
                "Only non-empty text messages are supported"
                if not isinstance(text, str) or not text.strip()
                else "Invalid chat request"
            )
        return BridgeMessageBuilder.error(request_id, reason)

    @staticmethod
    def bridge_chat_reply(request_id: str, text: str, final: bool = True) -> Dict[str, Any]:
        """Convert a QwenPaw text response to the Bridge wire format."""
        return BridgeMessageBuilder.chat_reply(request_id, text, final)

    @staticmethod
    def bridge_error(request_id: str, reason: str) -> Dict[str, Any]:
        """Convert a QwenPaw processing failure to the Bridge wire format."""
        return BridgeMessageBuilder.error(request_id, reason)


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
        bot_prefix: str = "",
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
            # Bridge permits a single reply per request. Suppress QwenPaw's
            # intermediate tool/thinking messages so the final answer retains
            # the only available response slot.
            show_tool_details=False,
            filter_tool_messages=True,
            no_text_debounce=no_text_debounce,
            filter_thinking=True,
            dm_policy=dm_policy,
            group_policy=group_policy,
            allow_from=allow_from,
            deny_message=deny_message,
            require_mention=require_mention,
        )
        self.enabled = enabled
        self.bot_prefix = bot_prefix

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
        # Identity fields are optional overrides only. Leave them empty when the
        # operator did not set them so the Bridge keeps the name/command that were
        # configured for this Agent in its panel. Forcing "QwenPaw"/"qwenpaw" here
        # would reset another instance's command on connect and make it impossible
        # to route to more than one QwenPaw instance from the same Bridge.
        self._agent_name = agent_name.strip() if agent_name else ""
        self._command = command.strip() if command else ""

        # Runtime state.
        self._ws: Any = None
        self._running = False
        self._listener_task: Optional[asyncio.Task] = None
        self._outbound_lock = asyncio.Lock()
        # Tracks whether a reply has already been sent for a given Bridge
        # request id. The Bridge closes its pending request as soon as it
        # receives a reply without ``final: false``; to keep the pending
        # request open across multi-segment replies (e.g. tool progress +
        # final answer) we emit ``final: false`` for every segment except
        # the terminal one, which we close via ``_on_process_completed``.
        self._reply_started: Dict[str, bool] = {}

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
            bot_prefix=getattr(config, "bot_prefix", "") or "",
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
        if self._listener_task is not None and not self._listener_task.done():
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
                    await self._send_raw(BridgeMessageBuilder.auth(
                        token=self._token,
                        agent_id=self._agent_id,
                        name=self._agent_name,
                        command=self._command,
                        description="QwenPaw Channel Plugin",
                    ))
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    auth = self._decode(raw)
                    if auth.get("type") != "auth_ok":
                        reason = auth.get("reason", "unknown")
                        logger.error("WeClawBot: authentication rejected — %s", reason)
                        # auth_fail is a configuration error (token or agent ID),
                        # not a transient transport failure. Retrying would only
                        # create a reconnect loop until configuration changes.
                        self._running = False
                        return
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
            await self._send_raw(BridgeMessageBuilder.pong())
            return
        if kind != "chat":
            if kind == "error":
                logger.warning(
                    "WeClawBot: Bridge error: %s", msg.get("reason", "unknown")
                )
            return

        # Use the protocol adapter to convert Bridge wire format → QwenPaw native.
        native = BridgeProtocolAdapter.native_from_bridge_chat(
            msg,
            channel_id=self.channel,
            agent_id=self._agent_id,
        )
        if native is None:
            error = BridgeProtocolAdapter.invalid_chat_error(msg)
            if error is not None:
                await self._send_raw(error)
            return

        # The request id travels in channel_meta, so replies are correlated
        # without a shared mutable route that tool-progress messages can consume.
        # Enqueue the native payload — the base class consume_one()
        # will call build_agent_request_from_native() and dispatch.
        if self._enqueue is not None:
            self._enqueue(native)

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
        # Request correlation is supplied in channel_meta; do not fall back to
        # a shared per-chat request ID because concurrent tool runs can overwrite it.
        request_id = (meta or {}).get("bridge_request_id")
        if not request_id:
            logger.warning(
                "WeClawBot: no Bridge request id for reply to %s; dropping reply",
                to_handle,
            )
            return
        try:
            # Emit every segment with final=False so the Bridge keeps the
            # pending request open until we explicitly close it in
            # _on_process_completed. A missing/true final on the first segment
            # would make the Bridge close the pending request early and drop
            # later segments (logged as "收到未知请求 ID 的回复").
            await self._send_raw(
                BridgeProtocolAdapter.bridge_chat_reply(
                    request_id=request_id, text=text, final=False
                )
            )
            self._reply_started[request_id] = True
        except Exception:
            logger.exception("WeClawBot: failed to send reply for %s", request_id)

    async def _on_process_completed(
        self,
        request: Any,
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """Close the Bridge pending request with a terminal ``final: true``.

        Overrides the (no-op) base hook. QwenPaw calls this once after all
        reply segments for a request have been sent. We use it to emit the
        ``final: true`` packet that lets the Bridge release the pending request
        instead of timing it out or rejecting later segments.
        """
        await super()._on_process_completed(request, to_handle, send_meta)
        request_id = (send_meta or {}).get("bridge_request_id")
        if request_id and self._reply_started.pop(request_id, False):
            try:
                await self._send_raw(
                    BridgeProtocolAdapter.bridge_chat_reply(
                        request_id=request_id, text="", final=True
                    )
                )
            except Exception:
                logger.exception(
                    "WeClawBot: failed to send final reply for %s", request_id
                )

    async def send_media(self, to_handle: str, part: Any, meta: Optional[Dict[str, Any]] = None) -> None:
        """Report unsupported media instead of silently losing a response."""
        request_id = (meta or {}).get("bridge_request_id")
        if not request_id:
            logger.warning("WeClawBot: no Bridge request id for media reply to %s", to_handle)
            return
        await self._reply_error(request_id, "Media responses are not supported")

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
            await self._send_raw(BridgeProtocolAdapter.bridge_error(request_id, reason))
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
