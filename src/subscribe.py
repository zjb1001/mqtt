from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, List, Set, Optional
import asyncio
from datetime import datetime

from .session import SessionState, QoSMessage
from .will_message import QoSLevel

class MessageType(IntEnum):
    SUBSCRIBE = 8
    SUBACK = 9

@dataclass
class SubscribePacket:
    packet_id: int
    topic_filters: List[tuple[str, QoSLevel]]
    
    def encode(self) -> bytes:
        """Encode SUBSCRIBE packet to bytes"""
        # Variable header
        packet = bytearray()
        # Packet identifier (2 bytes)
        packet.extend(self.packet_id.to_bytes(2, 'big'))
        
        # Payload - topic filters and QoS
        for topic, qos in self.topic_filters:
            # Topic length (2 bytes) + topic + QoS (1 byte)
            packet.extend(len(topic).to_bytes(2, 'big'))
            packet.extend(topic.encode())
            packet.extend(bytes([qos]))
        
        # Fixed header
        fixed_header = bytearray([MessageType.SUBSCRIBE << 4 | 0x02])  # QoS=1 required
        # Remaining length
        remaining_length = len(packet)
        while remaining_length > 0:
            byte = remaining_length & 0x7F
            remaining_length >>= 7
            if remaining_length > 0:
                byte |= 0x80
            fixed_header.append(byte)
            
        return bytes(fixed_header + packet)

@dataclass
class TopicNode:
    segment: str
    children: Dict[str, 'TopicNode']
    subscribers: Set[str]  # Set of client IDs
    qos_levels: Dict[str, QoSLevel]  # Map client ID to QoS
    is_wildcard: bool
    
    def __init__(self, segment: str):
        self.segment = segment
        self.children = {}
        self.subscribers = set()
        self.qos_levels = {}
        self.is_wildcard = '#' in segment or '+' in segment

class SubscriptionHandler:
    def __init__(self):
        self.topic_tree = TopicNode('')
        self.sessions: Dict[str, SessionState] = {}
        
    def _split_topic(self, topic: str) -> List[str]:
        """Split topic into segments"""
        return topic.split('/')
    
    def _add_topic_node(self, segments: List[str], client_id: str, qos: QoSLevel, node: TopicNode = None) -> None:
        """Add topic subscription to topic tree"""
        if node is None:
            node = self.topic_tree
            
        if not segments:
            node.subscribers.add(client_id)
            node.qos_levels[client_id] = qos
            return
            
        segment = segments[0]
        if segment not in node.children:
            node.children[segment] = TopicNode(segment)
            
        self._add_topic_node(segments[1:], client_id, qos, node.children[segment])
    
    def _match_topic(self, pattern: List[str], topic: List[str], node: TopicNode = None) -> Set[str]:
        """Match topic against pattern, return matching subscribers"""
        if node is None:
            node = self.topic_tree
            
        if not pattern or not topic:
            return node.subscribers
            
        matched_subscribers = set()
        
        # Handle wildcards
        if pattern[0] == '#':
            return node.subscribers
        elif pattern[0] == '+':
            for child in node.children.values():
                matched_subscribers.update(
                    self._match_topic(pattern[1:], topic[1:], child)
                )
        elif pattern[0] in node.children:
            if pattern[0] == topic[0]:
                matched_subscribers.update(
                    self._match_topic(pattern[1:], topic[1:], node.children[pattern[0]])
                )
                
        return matched_subscribers

    async def handle_subscribe(self, client_id: str, packet: SubscribePacket) -> List[QoSLevel]:
        """Handle SUBSCRIBE packet"""
        return_codes = []
        
        for topic, qos in packet.topic_filters:
            # Validate topic filter
            if not topic or '#' in topic[:-1] or '+' in topic and len(topic) > 1:
                return_codes.append(0x80)  # Failure
                continue
                
            # Add subscription to topic tree
            segments = self._split_topic(topic)
            self._add_topic_node(segments, client_id, qos)
            
            # Update session state
            if client_id in self.sessions:
                self.sessions[client_id].subscriptions[topic] = qos
                
            # Add granted QoS to return codes
            return_codes.append(qos)
            
        return return_codes
        
    async def send_suback(self, writer: asyncio.StreamWriter, packet_id: int, return_codes: List[QoSLevel]) -> None:
        """Send SUBACK packet"""
        # Variable header
        packet = bytearray()
        packet.extend(packet_id.to_bytes(2, 'big'))
        
        # Payload - return codes
        packet.extend(bytes(return_codes))
        
        # Fixed header
        fixed_header = bytearray([MessageType.SUBACK << 4])
        # Remaining length
        remaining_length = len(packet)
        while remaining_length > 0:
            byte = remaining_length & 0x7F
            remaining_length >>= 7
            if remaining_length > 0:
                byte |= 0x80
            fixed_header.append(byte)
            
        writer.write(bytes(fixed_header + packet))
        await writer.drain()
        
    def get_matching_subscribers(self, topic: str) -> Dict[str, QoSLevel]:
        """Get all subscribers matching a topic"""
        topic_segments = self._split_topic(topic)
        matched_subscribers = self._match_topic(topic_segments, topic_segments)
        
        # Create map of client IDs to their QoS levels
        result = {}
        for client_id in matched_subscribers:
            # Find the most specific matching subscription for this client
            for pattern in self.sessions[client_id].subscriptions:
                if self._match_topic(self._split_topic(pattern), topic_segments):
                    result[client_id] = self.sessions[client_id].subscriptions[pattern]
                    break
                    
        return result