# MQTT Core Components Implementation Design

## 1. Broker Design

### Data Structure
```python
from dataclasses import dataclass
from typing import Dict, Set, Optional
from collections import defaultdict
import asyncio
from datetime import datetime

@dataclass
class Broker:
    clients: Dict[str, 'Client']  # Store connected clients
    topics: Dict[str, 'Topic']    # Manage topics
    subscriptions: Dict[str, list[str]]  # Map client IDs to topic subscriptions
    retained_messages: Dict[str, 'Message']  # Store retained messages per topic

    def __init__(self):
        self.clients = {}
        self.topics = {}
        self.subscriptions = defaultdict(list)
        self.retained_messages = {}
```

### Key Methods
```python
class BrokerMethods:
    async def handle_connection(self, client_id: str) -> None: ...
    async def route_message(self, message: 'Message') -> None: ...
    async def handle_subscription(self, client_id: str, topics: list[str]) -> None: ...
    async def handle_disconnection(self, client_id: str) -> None: ...
```

### Responsibilities
- Client connection management
- Message routing and distribution
- Subscription tracking
- Session state management
- Retained message handling

## 2. Client Design

### Data Structure
```python
@dataclass
class Session:
    clean_session: bool
    keep_alive_interval: int
    last_activity: datetime
    qos_messages: Dict[int, 'Message']  # Track QoS messages

@dataclass
class Client:
    id: str                       # Unique client identifier
    connection: asyncio.StreamWriter  # TCP connection details
    session: Session              # Session state
    subscriptions: Set[str]       # Subscribed topics
    message_queue: asyncio.Queue  # Pending messages
    will_message: Optional['Message']  # Last Will and Testament

    def __init__(self, client_id: str, connection: asyncio.StreamWriter):
        self.id = client_id
        self.connection = connection
        self.session = Session(clean_session=True, 
                             keep_alive_interval=60,
                             last_activity=datetime.now(),
                             qos_messages={})
        self.subscriptions = set()
        self.message_queue = asyncio.Queue()
        self.will_message = None
```

### Key Methods
```python
class ClientMethods:
    async def connect(self, broker: str, options: dict) -> None: ...
    async def publish(self, topic: str, message: 'Message', qos: int) -> None: ...
    async def subscribe(self, topics: list[str]) -> None: ...
    async def unsubscribe(self, topics: list[str]) -> None: ...
    async def disconnect(self) -> None: ...
```

### Responsibilities
- Maintain connection with broker
- Handle message publishing
- Manage subscriptions
- Process incoming messages
- Track QoS message state

## 3. Topic Design

### Data Structure
```python
@dataclass
class Topic:
    name: str                     # Full topic name
    subscribers: Set[str]         # Subscribed client IDs
    retained_message: Optional['Message']  # Optional retained message
    qos_levels: Dict[str, int]    # QoS levels per subscriber

class TopicNode:
    def __init__(self, segment: str):
        self.segment = segment    # Topic segment
        self.children = {}        # Child topics
        self.subscribers = set()  # Subscribers at this level
        self.is_wildcard = '#' in segment or '+' in segment
```

### Key Methods
```python
class TopicMethods:
    @staticmethod
    def match_topic(pattern: str, topic: str) -> bool: ...
    def add_subscriber(self, client_id: str, qos: int) -> None: ...
    def remove_subscriber(self, client_id: str) -> None: ...
    def set_retained_message(self, message: 'Message') -> None: ...
```

## 4. Message and Packet Integration Design

### Message Types
```python
from enum import IntEnum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, Protocol
from abc import ABC, abstractmethod

class MessageType(IntEnum):
    CONNECT = 1
    CONNACK = 2
    PUBLISH = 3
    PUBACK = 4
    PUBREC = 5
    PUBREL = 6
    PUBCOMP = 7
    SUBSCRIBE = 8
    SUBACK = 9
    UNSUBSCRIBE = 10
    UNSUBACK = 11
    PINGREQ = 12
    PINGRESP = 13
    DISCONNECT = 14

# Protocol for packet-message conversion
class PacketConverter(Protocol):
    def to_packet(self) -> 'Packet': ...
    @classmethod
    def from_packet(cls, packet: 'Packet') -> 'Message': ...

@dataclass
class Message(PacketConverter):
    """Base message class that all MQTT messages inherit from"""
    type: MessageType
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_packet(self) -> 'Packet':
        """Convert message to network packet"""
        return Packet(
            fixed_header=FixedHeader(
                message_type=self.type,
                dup_flag=False,
                qos_level=0,
                retain=False,
                remaining_length=0
            ),
            variable_header={},
            payload=None
        )
    
    @classmethod
    def from_packet(cls, packet: 'Packet') -> 'Message':
        """Create message from network packet"""
        return cls(type=packet.fixed_header.message_type)

@dataclass
class PublishMessage(Message):
    """Message for publishing data to topics"""
    id: int                      # Unique message identifier
    topic: str                   # Target topic
    payload: bytes               # Message content
    qos: int = 0                # Quality of Service level
    retain: bool = False        # Retain flag
    dup: bool = False          # Duplicate delivery flag
    
    def __post_init__(self):
        self.type = MessageType.PUBLISH
    
    def to_packet(self) -> 'Packet':
        packet = super().to_packet()
        packet.fixed_header.qos_level = self.qos
        packet.fixed_header.retain = self.retain
        packet.fixed_header.dup_flag = self.dup
        packet.variable_header = {
            'topic_name': self.topic,
            'packet_identifier': self.id if self.qos > 0 else None
        }
        packet.payload = self.payload
        return packet
    
    @classmethod
    def from_packet(cls, packet: 'Packet') -> 'PublishMessage':
        return cls(
            id=packet.get_identifier() or 0,
            topic=packet.variable_header['topic_name'],
            payload=packet.payload,
            qos=packet.fixed_header.qos_level,
            retain=packet.fixed_header.retain,
            dup=packet.fixed_header.dup_flag,
            type=MessageType.PUBLISH
        )
    
    def duplicate(self) -> 'PublishMessage':
        """Create duplicate message for retransmission"""
        return PublishMessage(
            id=self.id,
            topic=self.topic,
            payload=self.payload,
            qos=self.qos,
            retain=self.retain,
            dup=True
        )

class MessageHandler(ABC):
    """Interface for handling different message types"""
    @abstractmethod
    async def handle_publish(self, message: PublishMessage) -> None: ...
    @abstractmethod
    async def handle_subscribe(self, message: 'SubscribeMessage') -> None: ...
    @abstractmethod
    async def handle_unsubscribe(self, message: 'UnsubscribeMessage') -> None: ...

## 5. Packet Design for Network Transport

### Data Structure
```python
from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class FixedHeader:
    message_type: MessageType
    dup_flag: bool
    qos_level: int
    retain: bool
    remaining_length: int

@dataclass
class ConnectFlags:
    clean_session: bool
    will_flag: bool
    will_qos: int
    will_retain: bool
    username_flag: bool
    password_flag: bool

@dataclass
class Packet:
    fixed_header: FixedHeader
    variable_header: Dict[str, Any]
    payload: Optional[bytes] = None
    
    def __init__(self, message_type: MessageType):
        self.fixed_header = FixedHeader(
            message_type=message_type,
            dup_flag=False,
            qos_level=0,
            retain=False,
            remaining_length=0
        )
        self.variable_header = {}
        self.payload = None
```

### Key Methods
```python
class PacketMethods:
    def encode(self) -> bytes:
        """Encode packet into bytes for transmission"""
        ...
    
    @classmethod
    def decode(cls, buffer: bytes) -> 'Packet':
        """Decode received bytes into Packet object"""
        ...
    
    def validate(self) -> bool:
        """Validate packet structure and contents"""
        ...
        
    def get_identifier(self) -> Optional[int]:
        """Get packet identifier for QoS > 0"""
        ...

class PacketFactory:
    @staticmethod
    def create_connect(client_id: str, clean_session: bool = True) -> Packet: ...
    
    @staticmethod
    def create_publish(topic: str, payload: bytes, qos: int = 0) -> Packet: ...
    
    @staticmethod
    def create_subscribe(topics: list[tuple[str, int]]) -> Packet: ...
    
    @staticmethod
    def create_unsubscribe(topics: list[str]) -> Packet: ...
```

### Packet Types and Structures

1. **CONNECT Packet**
```python
@dataclass
class ConnectPacket(Packet):
    protocol_name: str = "MQTT"
    protocol_level: int = 4  # MQTT 3.1.1
    connect_flags: ConnectFlags = field(default_factory=ConnectFlags)
    keep_alive: int = 60
    client_id: str = ""
    will_topic: Optional[str] = None
    will_payload: Optional[bytes] = None
    username: Optional[str] = None
    password: Optional[bytes] = None
```

2. **PUBLISH Packet**
```python
@dataclass
class PublishPacket(Packet):
    topic_name: str
    packet_identifier: Optional[int]  # Required for QoS > 0
    payload: bytes
```

3. **SUBSCRIBE/UNSUBSCRIBE Packets**
```python
@dataclass
class SubscribePacket(Packet):
    packet_identifier: int
    topic_filters: list[tuple[str, int]]  # (topic, QoS) pairs

@dataclass
class UnsubscribePacket(Packet):
    packet_identifier: int
    topic_filters: list[str]
```

### Packet Handling Interface
```python
from abc import ABC, abstractmethod

class PacketHandler(ABC):
    @abstractmethod
    async def handle_connect(self, packet: ConnectPacket) -> None: ...
    
    @abstractmethod
    async def handle_publish(self, packet: PublishPacket) -> None: ...
    
    @abstractmethod
    async def handle_subscribe(self, packet: SubscribePacket) -> None: ...
    
    @abstractmethod
    async def handle_unsubscribe(self, packet: UnsubscribePacket) -> None: ...
    
    @abstractmethod
    async def handle_pingreq(self, packet: Packet) -> None: ...
    
    @abstractmethod
    async def handle_disconnect(self, packet: Packet) -> None: ...
```

## Implementation Considerations

### 1. Thread Safety
- Use asyncio for async/await pattern
- Implement locks and synchronization primitives
- Handle concurrent client connections
- Protect shared resources using Python's threading module

### 2. Memory Management
- Implement message cleanup strategies
- Handle session persistence using Python's pickle or databases
- Manage connection resources with context managers
- Use weakref for caching when appropriate

### 3. Performance Optimization
- Use appropriate Python data structures (dict, set)
- Implement connection pooling with asyncio
- Optimize topic matching with efficient algorithms
- Cache topic trees using functools.lru_cache

### 4. Error Handling
- Use Python's exception handling mechanisms
- Implement retry patterns with exponential backoff
- Use asyncio error handling for network issues
- Proper resource cleanup with context managers

## Interfaces Between Components

### 1. Broker-Client Interface
```python
from abc import ABC, abstractmethod

class BrokerClientInterface(ABC):
    @abstractmethod
    async def on_connect(self, client: Client) -> None: ...
    @abstractmethod
    async def on_disconnect(self, client: Client) -> None: ...
    @abstractmethod
    async def on_publish(self, client: Client, message: Message) -> None: ...
    @abstractmethod
    async def on_subscribe(self, client: Client, topics: list[str]) -> None: ...
    @abstractmethod
    async def on_unsubscribe(self, client: Client, topics: list[str]) -> None: ...
```

### 2. Message Handling Interface
```python
class MessageHandler(ABC):
    @abstractmethod
    async def handle_incoming(self, message: Message) -> None: ...
    @abstractmethod
    async def handle_outgoing(self, message: Message) -> None: ...
    @abstractmethod
    async def handle_qos(self, message: Message) -> None: ...
    @abstractmethod
    async def handle_retained(self, message: Message) -> None: ...
```

### 3. Topic Management Interface
```python
class TopicManager(ABC):
    @abstractmethod
    async def subscribe(self, client_id: str, topic: str, qos: int) -> None: ...
    @abstractmethod
    async def unsubscribe(self, client_id: str, topic: str) -> None: ...
    @abstractmethod
    async def publish(self, topic: str, message: Message) -> None: ...
    @abstractmethod
    def match_subscribers(self, topic: str) -> Set[str]: ...
```

## Testing Strategy

### 1. Unit Tests
- Use pytest for unit testing
- Test individual component functionality
- Mock external dependencies with unittest.mock
- Use pytest-asyncio for async tests

### 2. Integration Tests
- Test component interactions with pytest-integration
- Verify message flow with actual MQTT brokers
- Test connection handling with docker containers
- Validate QoS implementation end-to-end

### 3. Performance Tests
- Use pytest-benchmark for performance metrics
- Test concurrent connections with asyncio
- Profile memory usage with memory_profiler
- Measure topic tree performance with cProfile

## Next Steps

1. Set up Python project structure with poetry
2. Implement core data structures using dataclasses
3. Develop async functionality with asyncio
4. Add QoS support with proper retry logic
5. Implement session management with persistence
6. Add TLS support using Python's ssl module
7. Optimize performance using profiling tools
8. Add monitoring with Python logging and metrics

This design provides a foundation for building a robust MQTT implementation in Python, leveraging the language's strengths in asyncio, type hints, and modern features while maintaining clear separation of concerns.