from agentos.channels.adapters.dingtalk import DingTalkAdapter
from agentos.channels.adapters.discord import DiscordAdapter
from agentos.channels.adapters.feishu import FeishuAdapter
from agentos.channels.adapters.line import LINEAdapter
from agentos.channels.adapters.qq import QQAdapter
from agentos.channels.adapters.slack import SlackAdapter
from agentos.channels.adapters.telegram import TelegramAdapter
from agentos.channels.adapters.wechat import WeChatAdapter
from agentos.channels.adapters.wecom import WeComAdapter
from agentos.channels.adapters.whatsapp import WhatsAppAdapter

__all__ = [
    "WeChatAdapter",
    "WeComAdapter",
    "FeishuAdapter",
    "DingTalkAdapter",
    "QQAdapter",
    "SlackAdapter",
    "DiscordAdapter",
    "TelegramAdapter",
    "WhatsAppAdapter",
    "LINEAdapter",
]
