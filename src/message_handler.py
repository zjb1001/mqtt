from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Protocol, Set
import asyncio
from enum import IntEnum

from .will_message import QoSLevel
from .publish import PublishPacket, PublishHandler
from .session import QoSMessage, SessionState
from .subscribe import SubscriptionHandler

@dataclass
class Message:
    """Base message class that all MQTT messages inherit from"""
    type: int
    timestamp: datetime = datetime.now()

@dataclass
class RetainedMessage:
    """Retained message storage"""
    topic: str
    payload: bytes
    qos: QoSLevel
    timestamp: datetime
    last_modified: datetime

class MessageQueue:
    """Message queue implementation for handling messages"""
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.retained_messages: Dict[str, RetainedMessage] = {}
        self.inflight_messages: Dict[str, Dict[int, QoSMessage]] = {}
        
    async def put(self, message: Message) -> None:
        """Add message to queue"""
        await self.queue.put(message)
        
    async def get(self) -> Message:
        """Get next message from queue"""
        return await self.queue.get()
    
    def store_retained_message(self, topic: str, message: RetainedMessage) -> None:
        """Store retained message"""
        self.retained_messages[topic] = message
        
    def get_retained_message(self, topic: str) -> Optional[RetainedMessage]:
        """Get retained message for topic"""
        return self.retained_messages.get(topic)
    
    def track_inflight_message(self, client_id: str, message: QoSMessage) -> None:
        """Track inflight QoS message"""
        if client_id not in self.inflight_messages:
            self.inflight_messages[client_id] = {}
        self.inflight_messages[client_id][message.message_id] = message

class MessageHandler:
    """Main message handling class"""
    def __init__(self):
        self.message_queue = MessageQueue()
        self.publish_handler = PublishHandler()
        self.subscription_handler = SubscriptionHandler()
        self.sessions: Dict[str, SessionState] = {}
        self.retry_interval: float = 5.0
        self.max_retries: int = 3
        
    async def start(self) -> asyncio.Task:
        """Start message handling loop"""
        task = asyncio.create_task(self._process_message_queue())
        return task
        
    async def _process_message_queue(self) -> None:
        """Main message processing loop"""
        while True:
            message = await self.message_queue.get()
            try:
                if isinstance(message, PublishPacket):
                    await self._handle_publish(message)
            except Exception as e:
                print(f"Error processing message: {e}")
                
    async def _handle_publish(self, packet: PublishPacket) -> None:
        """Handle publish message"""
        # Store retained message if needed
        if packet.retain:
            retained_msg = RetainedMessage(
                topic=packet.topic,
                payload=packet.payload,
                qos=packet.qos,
                timestamp=datetime.now(),
                last_modified=datetime.now()
            )
            self.message_queue.store_retained_message(packet.topic, retained_msg)
            
        # Get matching subscribers
        subscribers = self.subscription_handler.get_matching_subscribers(packet.topic)
        
        # Deliver to subscribers
        for client_id, qos in subscribers.items():
            # Use the lower of the publish QoS and subscription QoS
            effective_qos = min(packet.qos, qos)
            
            # Only process if client has active session
            if client_id not in self.sessions:
                continue
                
            session = self.sessions[client_id]

            # Create QoS tracking message for QoS > 0
            if effective_qos > QoSLevel.AT_MOST_ONCE:
                qos_msg = QoSMessage(
                    message_id=self.publish_handler._get_next_packet_id(),
                    qos_level=effective_qos,
                    timestamp=datetime.now(),
                    topic=packet.topic,  # Add topic for reference
                    payload=packet.payload  # Add payload for message content
                )
                
                # Track message and add to session's pending messages
                self.message_queue.track_inflight_message(client_id, qos_msg)
                session.pending_messages[qos_msg.message_id] = qos_msg
                
                # Start QoS retry handler
                asyncio.create_task(
                    self._handle_qos_retry(client_id, qos_msg, packet)
                )
                
    async def _handle_qos_retry(self, client_id: str, qos_msg: QoSMessage, packet: PublishPacket) -> None:
        """Handle QoS message retry logic"""
        while qos_msg.retry_count < self.max_retries and not qos_msg.ack_received:
            await asyncio.sleep(self.retry_interval * (qos_msg.retry_count + 1))
            
            if qos_msg.ack_received:
                break
                
            qos_msg.retry_count += 1
            
            if client_id in self.sessions:
                # Retransmit message
                # Note: Actual transmission would be handled by connection manager
                packet.dup = True
                
        if not qos_msg.ack_received and client_id in self.sessions:
            # Clean up failed delivery
            session = self.sessions[client_id]
            session.pending_messages.pop(qos_msg.message_id, None)
            
    async def handle_message_acknowledgment(self, client_id: str, packet_id: int, ack_type: str) -> None:
        """Handle message acknowledgments (PUBACK, PUBREC, PUBREL, PUBCOMP)"""
        if client_id in self.sessions:
            session = self.sessions[client_id]
            if packet_id in session.pending_messages:
                qos_msg = session.pending_messages[packet_id]
                
                if ack_type == "PUBACK" or ack_type == "PUBCOMP":
                    qos_msg.ack_received = True
                    qos_msg.state = "COMPLETED"
                    session.pending_messages.pop(packet_id, None)
                elif ack_type == "PUBREC":
                    qos_msg.state = "PUBREC_RECEIVED"
                elif ack_type == "PUBREL":
                    qos_msg.state = "PUBREL_RECEIVED"
                    
    def get_session_messages(self, client_id: str) -> Dict[int, QoSMessage]:
        """Get pending messages for a client session"""
        if client_id in self.sessions:
            return self.sessions[client_id].pending_messages
        return {}