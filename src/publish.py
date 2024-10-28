from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Optional, Dict, Any
import asyncio

from .will_message import QoSLevel
from .session import QoSMessage

class MessageType(IntEnum):
    PUBLISH = 3
    PUBACK = 4
    PUBREC = 5
    PUBREL = 6
    PUBCOMP = 7

@dataclass
class PublishPacket:
    topic: str
    payload: bytes
    qos: QoSLevel = QoSLevel.AT_MOST_ONCE
    retain: bool = False
    dup: bool = False
    packet_id: Optional[int] = None

    def encode(self) -> bytes:
        """Encode the PUBLISH packet into bytes"""
        # Variable header
        packet = bytearray()
        
        # Topic name
        packet.extend(len(self.topic).to_bytes(2, 'big'))
        packet.extend(self.topic.encode())
        
        # Packet identifier (only for QoS > 0)
        if self.qos != QoSLevel.AT_MOST_ONCE:
            if self.packet_id is None:
                raise ValueError("Packet ID required for QoS > 0")
            packet.extend(self.packet_id.to_bytes(2, 'big'))
        
        # Payload
        packet.extend(self.payload)
        
        # Fixed header
        fixed_header = bytearray()
        header_byte = MessageType.PUBLISH << 4
        if self.dup:
            header_byte |= 0x08
        header_byte |= (self.qos << 1)
        if self.retain:
            header_byte |= 0x01
        fixed_header.append(header_byte)
        
        # Add remaining length
        remaining_length = len(packet)
        while remaining_length > 0:
            byte = remaining_length & 0x7F
            remaining_length >>= 7
            if remaining_length > 0:
                byte |= 0x80
            fixed_header.append(byte)
        
        return bytes(fixed_header + packet)

class PublishHandler:
    def __init__(self):
        self.next_packet_id: int = 1
        self.pending_qos_messages: Dict[int, QoSMessage] = {}
        self.retry_interval: float = 5.0  # seconds
        self.max_retries: int = 3

    def _get_next_packet_id(self) -> int:
        """Generate next packet ID for QoS > 0 messages"""
        packet_id = self.next_packet_id
        self.next_packet_id = (self.next_packet_id + 1) % 65536  # Keep within 16 bits
        return packet_id

    async def publish_message(self, topic: str, payload: bytes, qos: QoSLevel = QoSLevel.AT_MOST_ONCE, 
                            retain: bool = False) -> Optional[int]:
        """Publish a message with the specified QoS level"""
        packet_id = None
        if qos != QoSLevel.AT_MOST_ONCE:
            packet_id = self._get_next_packet_id()
            
            # Create QoS tracking message
            qos_message = QoSMessage(
                message_id=packet_id,
                qos_level=qos,
                timestamp=datetime.now()
            )
            self.pending_qos_messages[packet_id] = qos_message
        
        # Create and encode publish packet
        packet = PublishPacket(
            topic=topic,
            payload=payload,
            qos=qos,
            retain=retain,
            packet_id=packet_id
        )
        
        # Start QoS handling process if needed
        if qos != QoSLevel.AT_MOST_ONCE:
            asyncio.create_task(self._handle_qos_retry(packet))
        
        return packet_id

    async def _handle_qos_retry(self, packet: PublishPacket) -> None:
        """Handle QoS retry logic for QoS 1 and 2"""
        if packet.packet_id is None or packet.packet_id not in self.pending_qos_messages:
            return
        
        qos_message = self.pending_qos_messages[packet.packet_id]
        while qos_message.retry_count < self.max_retries and not qos_message.ack_received:
            await asyncio.sleep(self.retry_interval)
            
            if qos_message.ack_received:
                break
                
            qos_message.retry_count += 1
            packet.dup = True  # Set DUP flag for retransmission
            
            # Retransmit packet
            # Note: Actual network transmission would be handled by a connection manager
            
        if not qos_message.ack_received:
            # Handle failed delivery
            del self.pending_qos_messages[packet.packet_id]

    async def handle_puback(self, packet_id: int) -> None:
        """Handle PUBACK packet for QoS 1"""
        if packet_id in self.pending_qos_messages:
            qos_message = self.pending_qos_messages[packet_id]
            qos_message.ack_received = True
            qos_message.state = "COMPLETED"
            del self.pending_qos_messages[packet_id]

    async def handle_pubrec(self, packet_id: int) -> None:
        """Handle PUBREC packet for QoS 2 - first phase"""
        if packet_id in self.pending_qos_messages:
            qos_message = self.pending_qos_messages[packet_id]
            qos_message.state = "PUBREC_RECEIVED"
            # Send PUBREL
            # Note: Actual network transmission would be handled by a connection manager

    async def handle_pubcomp(self, packet_id: int) -> None:
        """Handle PUBCOMP packet for QoS 2 - final phase"""
        if packet_id in self.pending_qos_messages:
            qos_message = self.pending_qos_messages[packet_id]
            qos_message.ack_received = True
            qos_message.state = "COMPLETED"
            del self.pending_qos_messages[packet_id]