from dataclasses import dataclass
from enum import IntEnum

class QoSLevel(IntEnum):
    AT_MOST_ONCE = 0
    AT_LEAST_ONCE = 1
    EXACTLY_ONCE = 2

@dataclass
class WillMessage:
    topic: str
    payload: bytes
    qos: QoSLevel
    retain: bool
    delay_interval: int = 0  # MQTT 5.0 feature

    def __post_init__(self):
        if self.delay_interval < 0:
            raise ValueError("Will delay interval cannot be negative")