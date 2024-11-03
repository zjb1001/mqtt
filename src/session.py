from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional
from .will_message import QoSLevel

@dataclass
class SessionState:
    client_id: str
    clean_session: bool
    subscriptions: Dict[str, QoSLevel]
    pending_messages: Dict[int, 'QoSMessage']
    timestamp: datetime

@dataclass
class QoSMessage:
    message_id: int
    qos_level: QoSLevel
    timestamp: datetime
    retry_count: int = 0
    state: str = "PENDING"
    ack_received: bool = False