# MQTT Key Features Design Document

## 1. Quality of Service (QoS) Levels

### Data Structures

```python
from enum import IntEnum
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

class QoSLevel(IntEnum):
    AT_MOST_ONCE = 0    # Fire and forget
    AT_LEAST_ONCE = 1   # Acknowledged delivery
    EXACTLY_ONCE = 2    # Assured delivery

@dataclass
class QoSMessage:
    message_id: int
    qos_level: QoSLevel
    timestamp: datetime
    retry_count: int = 0
    state: str = "PENDING"
    ack_received: bool = False
```

### Interface Definition

```python
from abc import ABC, abstractmethod

class QoSHandler(ABC):
    @abstractmethod
    async def handle_publish(self, message: PublishMessage) -> None:
        """Handle outgoing publish message based on QoS level"""
        pass
    
    @abstractmethod
    async def handle_puback(self, message_id: int) -> None:
        """Handle PUBACK for QoS 1"""
        pass
    
    @abstractmethod
    async def handle_pubrec(self, message_id: int) -> None:
        """Handle PUBREC for QoS 2 - first phase"""
        pass
    
    @abstractmethod
    async def handle_pubrel(self, message_id: int) -> None:
        """Handle PUBREL for QoS 2 - second phase"""
        pass
    
    @abstractmethod
    async def handle_pubcomp(self, message_id: int) -> None:
        """Handle PUBCOMP for QoS 2 - final phase"""
        pass
```

## 2. Retained Messages

### Data Structures

```python
@dataclass
class RetainedMessage:
    topic: str
    payload: bytes
    qos: QoSLevel
    timestamp: datetime
    last_modified: datetime
```

### Interface Definition

```python
class RetainedMessageHandler(ABC):
    @abstractmethod
    async def store_retained_message(self, topic: str, message: RetainedMessage) -> None:
        """Store a retained message for a topic"""
        pass
    
    @abstractmethod
    async def get_retained_message(self, topic: str) -> Optional[RetainedMessage]:
        """Retrieve retained message for a topic"""
        pass
    
    @abstractmethod
    async def delete_retained_message(self, topic: str) -> None:
        """Delete retained message for a topic"""
        pass
    
    @abstractmethod
    async def send_retained_messages(self, client: Client, topics: list[str]) -> None:
        """Send retained messages to a newly subscribed client"""
        pass
```

## 3. Last Will and Testament (LWT)

### Data Structures

```python
@dataclass
class WillMessage:
    topic: str
    payload: bytes
    qos: QoSLevel
    retain: bool
    delay_interval: int = 0  # MQTT 5.0 feature
```

### Interface Definition

```python
class WillMessageHandler(ABC):
    @abstractmethod
    async def store_will_message(self, client_id: str, will: WillMessage) -> None:
        """Store LWT message for a client"""
        pass
    
    @abstractmethod
    async def remove_will_message(self, client_id: str) -> None:
        """Remove LWT message when client disconnects cleanly"""
        pass
    
    @abstractmethod
    async def publish_will_message(self, client_id: str) -> None:
        """Publish LWT message when client disconnects unexpectedly"""
        pass
```

## 4. Keep-Alive Mechanism

### Data Structures

```python
@dataclass
class KeepAliveConfig:
    interval: int  # in seconds
    tolerance: float = 1.5  # multiplier for keep-alive timeout
    last_ping: Optional[datetime] = None
    ping_pending: bool = False
```

### Interface Definition

```python
class KeepAliveHandler(ABC):
    @abstractmethod
    async def start_keep_alive(self, client: Client) -> None:
        """Start keep-alive monitoring for a client"""
        pass
    
    @abstractmethod
    async def handle_ping(self, client: Client) -> None:
        """Process PINGREQ from client"""
        pass
    
    @abstractmethod
    async def handle_pong(self, client: Client) -> None:
        """Process PINGRESP from broker"""
        pass
    
    @abstractmethod
    async def check_keep_alive_timeout(self, client: Client) -> bool:
        """Check if client has exceeded keep-alive timeout"""
        pass
```

## 5. Clean/Persistent Sessions

### Data Structures

```python
@dataclass
class SessionState:
    client_id: str
    clean_session: bool
    subscriptions: Dict[str, QoSLevel]
    pending_messages: Dict[int, QoSMessage]
    timestamp: datetime
    
@dataclass
class SessionManager:
    active_sessions: Dict[str, SessionState]
    persistent_sessions: Dict[str, SessionState]
```

### Interface Definition

```python
class SessionHandler(ABC):
    @abstractmethod
    async def create_session(self, client: Client, clean_session: bool) -> None:
        """Create new session for client"""
        pass
    
    @abstractmethod
    async def restore_session(self, client_id: str) -> Optional[SessionState]:
        """Restore existing session for returning client"""
        pass
    
    @abstractmethod
    async def save_session(self, client_id: str, state: SessionState) -> None:
        """Save session state for persistence"""
        pass
    
    @abstractmethod
    async def clear_session(self, client_id: str) -> None:
        """Clear session state on clean disconnect"""
        pass
```

## Integration with Existing Components

### 1. Broker Integration

```python
class EnhancedBroker(Broker):
    def __init__(self):
        super().__init__()
        self.qos_handler = QoSHandlerImpl()
        self.retained_handler = RetainedMessageHandlerImpl()
        self.will_handler = WillMessageHandlerImpl()
        self.keep_alive_handler = KeepAliveHandlerImpl()
        self.session_handler = SessionHandlerImpl()
```

### 2. Client Integration

```python
class EnhancedClient(Client):
    def __init__(self, client_id: str, connection: asyncio.StreamWriter):
        super().__init__(client_id, connection)
        self.keep_alive_config = KeepAliveConfig(interval=60)
        self.will_message: Optional[WillMessage] = None
        self.qos_messages: Dict[int, QoSMessage] = {}
```

### 3. Message Integration

```python
@dataclass
class EnhancedMessage(Message):
    qos_level: QoSLevel = QoSLevel.AT_MOST_ONCE
    retain: bool = False
    is_will: bool = False
```

## Implementation Guidelines

1. **QoS Implementation**
   - Use asyncio for handling message acknowledgments
   - Implement message ID generation and tracking
   - Handle message retransmission with exponential backoff
   - Maintain message state machines for QoS 2

2. **Retained Messages**
   - Use persistent storage for retained messages
   - Implement efficient topic matching for retrieval
   - Handle message updates and deletions
   - Optimize memory usage for large numbers of retained messages

3. **Will Messages**
   - Store will messages in memory with client session
   - Implement timeout mechanism for delayed will messages
   - Handle will message updates during client session
   - Clean up will messages appropriately

4. **Keep-Alive**
   - Use asyncio timers for keep-alive monitoring
   - Implement ping/pong message handling
   - Handle network interruptions gracefully
   - Optimize keep-alive intervals based on network conditions

5. **Session Management**
   - Implement session persistence using appropriate storage
   - Handle session restoration efficiently
   - Manage memory usage for session state
   - Implement session expiry (MQTT 5.0 feature)

## Testing Requirements

1. **QoS Testing**
   - Test all QoS level combinations
   - Verify message ordering
   - Test network failure scenarios
   - Measure delivery guarantees

2. **Retained Message Testing**
   - Test message persistence
   - Verify topic matching
   - Test concurrent modifications
   - Check memory usage

3. **Will Message Testing**
   - Test normal and abnormal disconnections
   - Verify will message delivery
   - Test will message updates
   - Check delay intervals

4. **Keep-Alive Testing**
   - Test timeout detection
   - Verify ping/pong handling
   - Test network interruptions
   - Measure timing accuracy

5. **Session Testing**
   - Test session persistence
   - Verify state restoration
   - Test concurrent sessions
   - Check resource cleanup