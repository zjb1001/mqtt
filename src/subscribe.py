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
        return topic.split('/')
    
    def _add_topic_node(self, segments: List[str], client_id: str, qos: QoSLevel, node: TopicNode = None) -> None:
        """Add topic subscription to topic tree and manage subscription state
    
        Args:
            segments: Remaining segments of the topic filter
            client_id: Client ID to subscribe
            qos: QoS level for the subscription
            node: Current node in topic tree (None for root)
        """
        # Initialize root node if needed
        if node is None:
            node = self.topic_tree
        
        # Base case: empty segments
        if not segments:
            node.subscribers.add(client_id)
            node.qos_levels[client_id] = qos
            return
    
        # Get current segment
        segment = segments[0]
    
        # Create new node if needed
        if segment not in node.children:
            node.children[segment] = TopicNode(segment)
    
        # Handle wildcard subscription
        if segment == '#':
            # MQTT spec: '#' must be the last segment
            node.subscribers.add(client_id)
            node.qos_levels[client_id] = qos
            return
        
        # Handle single level wildcard subscription
        if segment == '+':
            node.subscribers.add(client_id)
            node.qos_levels[client_id] = qos
        
        # Recursive case: continue with remaining segments
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

    def _validate_topic_filter(self, topic: str) -> bool:
        """
        Validate topic filter according to MQTT rules:
        - Single-level wildcard (+) can be used at any level but must occupy entire level
        - Multi-level wildcard (#) must be the last character
        - Neither wildcard can be used within a level
        """
        if not topic:
            return False
            
        segments = topic.split('/')
        
        # Check each segment
        for i, segment in enumerate(segments):
            # Empty segment (double slash) is invalid
            if not segment:
                return False
                
            # Check for invalid wildcard usage
            if '+' in segment and segment != '+':
                return False  # + must occupy entire level
                
            if '#' in segment:
                if segment != '#' or i != len(segments) - 1:
                    return False  # # must be alone and at last position
                    
        return True
        
    def _validate_qos(self, qos: int) -> bool:
        """Validate QoS level is 0, 1, or 2"""
        return isinstance(qos, int) and 0 <= qos <= 2

    async def handle_subscribe(self, client_id: str, packet: SubscribePacket) -> List[QoSLevel]:
        """
        Handle SUBSCRIBE packet according to MQTT protocol.
        Returns a list of granted QoS levels or failure codes (0x80).
        """
        return_codes = []
        
        for topic, qos in packet.topic_filters:
            # Validate QoS level
            if not self._validate_qos(qos):
                return_codes.append(0x80)  # Failure
                continue
                
            # Validate topic filter
            if not self._validate_topic_filter(topic):
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
        # """Get all subscribers matching a topic"""
        topic_segments = topic.split('/')
        result = {}

        # Iterate through all clients and their subscriptions
        for client_id, session in self.sessions.items():
            # Check each subscription pattern for matches
            for pattern, qos in session.subscriptions.items():
                if self._match_topic(pattern.split('/'), topic_segments):
                    result[client_id] = qos

        return result