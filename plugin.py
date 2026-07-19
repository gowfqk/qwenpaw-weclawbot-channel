# -*- coding: utf-8 -*-
"""WeClawBot Bridge channel plugin entry point."""

import logging

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class WeClawBotChannelPlugin:
    """WeClawBot-Bridge WS Remote Agent channel plugin."""

    def register(self, api: PluginApi) -> None:
        from .channel import WeClawBotChannel

        api.register_channel(
            channel_class=WeClawBotChannel,
            label="WeClawBot Bridge",
            description="Connect QwenPaw to WeChat through WeClawBot-Bridge WS Remote Agent",
            icon="💬",
            doc_url={
                "zh": "https://github.com/gowfqk/qwenpaw-weclawbot-channel",
                "en": "https://github.com/gowfqk/qwenpaw-weclawbot-channel",
            },
            config_fields=[
                {
                    "name": "token",
                    "label": "WS Token",
                    "type": "password",
                    "required": True,
                    "placeholder": "Bridge WS Remote Agent Token",
                },
                {
                    "name": "bridge_url",
                    "label": "Bridge URL",
                    "type": "text",
                    "required": True,
                    "placeholder": "wss://<your-bridge-url>/ws/agent",
                },
                {
                    "name": "agent_id",
                    "label": "Agent ID",
                    "type": "text",
                    "required": False,
                    "placeholder": "qwenpaw",
                    "default": "qwenpaw",
                },
                {
                    "name": "agent_name",
                    "label": "Agent Name",
                    "type": "text",
                    "required": False,
                    "placeholder": "留空则沿用 Bridge 面板配置",
                },
                {
                    "name": "command",
                    "label": "Command Alias",
                    "type": "text",
                    "required": False,
                    "placeholder": "留空则沿用 Bridge 面板配置",
                },
            ],
        )
        logger.info("✓ WeClawBot Bridge channel registered")


plugin = WeClawBotChannelPlugin()
