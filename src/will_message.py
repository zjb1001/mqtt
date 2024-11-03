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
        if not isinstance(self.payload, bytes):
            raise TypeError("Payload must be bytes type")
            
        if not isinstance(self.delay_interval, int):
            raise TypeError("Delay interval must be integer type")
            
        if self.delay_interval < 0:
            raise ValueError("Will delay interval cannot be negative")
            
        if not self.topic:
            raise ValueError("Will topic cannot be empty")
            
        if '+' in self.topic or '#' in self.topic:
            raise ValueError("Will topic cannot contain wildcards (+ or #)")
            
        if not isinstance(self.qos, QoSLevel):
            try:
                self.qos = QoSLevel(self.qos)
            except ValueError:
                raise ValueError(f"Invalid QoS value: {self.qos}. Must be 0, 1, or 2")
