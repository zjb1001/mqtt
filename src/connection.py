import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any
from enum import IntEnum

from src.session import SessionState
from src.will_message import WillMessage

class MessageType(IntEnum):
    CONNECT = 1
    CONNACK = 2

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
class ConnectPacket:
    client_id: str
    clean_session: bool = True
    keep_alive: int = 60
    username: Optional[str] = None
    password: Optional[bytes] = None
    will_message: Optional['WillMessage'] = None

    def encode(self) -> bytes:
        """Encode the CONNECT packet into bytes"""
        # Protocol name and level
        packet = bytearray(b'\x00\x04MQTT\x04')  # MQTT 3.1.1
        
        # Connect flags
        flags = 0
        if self.clean_session:
            flags |= 0x02
        if self.username:
            flags |= 0x80
        if self.password:
            flags |= 0x40
        if self.will_message:
            flags |= 0x04
            flags |= (self.will_message.qos << 3)
            if self.will_message.retain:
                flags |= 0x20
        packet.append(flags)
        
        # Keep alive (16 bits)
        packet.extend(self.keep_alive.to_bytes(2, 'big'))
        
        # Client ID
        packet.extend(len(self.client_id).to_bytes(2, 'big'))
        packet.extend(self.client_id.encode())
        
        # Will message if present
        if self.will_message:
            packet.extend(len(self.will_message.topic).to_bytes(2, 'big'))
            packet.extend(self.will_message.topic.encode())
            packet.extend(len(self.will_message.payload).to_bytes(2, 'big'))
            packet.extend(self.will_message.payload)
        
        # Username if present
        if self.username:
            packet.extend(len(self.username).to_bytes(2, 'big'))
            packet.extend(self.username.encode())
        
        # Password if present
        if self.password:
            packet.extend(len(self.password).to_bytes(2, 'big'))
            packet.extend(self.password)
        
        # Add fixed header
        fixed_header = bytearray([MessageType.CONNECT << 4])
        remaining_length = len(packet)
        while remaining_length > 0:
            byte = remaining_length & 0x7F
            remaining_length >>= 7
            if remaining_length > 0:
                byte |= 0x80
            fixed_header.append(byte)
        
        return bytes(fixed_header + packet)

class ConnectionHandler:
    def __init__(self):
        self.connections: Dict[str, asyncio.StreamWriter] = {}
        self.session_states: Dict[str, 'SessionState'] = {}

    async def handle_new_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle incoming connection from client"""
        try:
            # Read CONNECT packet
            first_byte = await reader.read(1)
            if not first_byte or first_byte[0] >> 4 != MessageType.CONNECT:
                writer.close()
                return

            # Read remaining length
            remaining_length = 0
            multiplier = 1
            while True:
                byte = (await reader.read(1))[0]
                remaining_length += (byte & 0x7F) * multiplier
                if byte & 0x80 == 0:
                    break
                multiplier *= 128

            # Read the rest of the packet
            packet_data = await reader.read(remaining_length)
            connect_packet = self._decode_connect_packet(packet_data)

            # Process CONNECT packet
            success, session_present = await self._process_connect(connect_packet, writer)
            
            # Send CONNACK
            await self._send_connack(writer, success, session_present)

            if success:
                self.connections[connect_packet.client_id] = writer

        except Exception as e:
            print(f"Connection error: {e}")
            writer.close()

    def _decode_connect_packet(self, data: bytes) -> ConnectPacket:
        """Decode CONNECT packet from bytes"""
        pos = 0
        
        # Protocol name and level
        protocol_name_len = int.from_bytes(data[pos:pos+2], 'big')
        pos += 2
        protocol_name = data[pos:pos+protocol_name_len].decode()
        pos += protocol_name_len
        protocol_level = data[pos]
        pos += 1
        
        # Connect flags
        flags = data[pos]
        pos += 1
        clean_session = bool(flags & 0x02)
        will_flag = bool(flags & 0x04)
        will_qos = (flags >> 3) & 0x03
        will_retain = bool(flags & 0x20)
        username_flag = bool(flags & 0x80)
        password_flag = bool(flags & 0x40)
        
        # Keep alive
        keep_alive = int.from_bytes(data[pos:pos+2], 'big')
        pos += 2
        
        # Client ID
        client_id_len = int.from_bytes(data[pos:pos+2], 'big')
        pos += 2
        client_id = data[pos:pos+client_id_len].decode()
        pos += client_id_len
        
        # Will message
        will_message = None
        if will_flag:
            will_topic_len = int.from_bytes(data[pos:pos+2], 'big')
            pos += 2
            will_topic = data[pos:pos+will_topic_len].decode()
            pos += will_topic_len
            
            will_payload_len = int.from_bytes(data[pos:pos+2], 'big')
            pos += 2
            will_payload = data[pos:pos+will_payload_len]
            pos += will_payload_len
            
            from .will_message import WillMessage, QoSLevel
            will_message = WillMessage(
                topic=will_topic,
                payload=will_payload,
                qos=QoSLevel(will_qos),
                retain=will_retain
            )
        
        # Username
        username = None
        if username_flag:
            username_len = int.from_bytes(data[pos:pos+2], 'big')
            pos += 2
            username = data[pos:pos+username_len].decode()
            pos += username_len
        
        # Password
        password = None
        if password_flag:
            password_len = int.from_bytes(data[pos:pos+2], 'big')
            pos += 2
            password = data[pos:pos+password_len]
            pos += password_len
        
        return ConnectPacket(
            client_id=client_id,
            clean_session=clean_session,
            keep_alive=keep_alive,
            username=username,
            password=password,
            will_message=will_message
        )

    async def _process_connect(self, packet: ConnectPacket, writer: asyncio.StreamWriter) -> tuple[bool, bool]:
        """Process CONNECT packet and return (success, session_present)"""
        # Check if client ID already exists
        if packet.client_id in self.connections:
            old_writer = self.connections[packet.client_id]
            await old_writer.drain()
            old_writer.close()
        
        # Update to new writer
        self.connections[packet.client_id] = writer  # Update to new writer

        # Handle session state
        session_present = False
        if packet.client_id in self.session_states and not packet.clean_session:
            session_present = True
        elif packet.clean_session:
            self.session_states.pop(packet.client_id, None)
        
        # Create new session state if needed
        if not session_present:
            self.session_states[packet.client_id] = SessionState(
                client_id=packet.client_id,
                clean_session=packet.clean_session,
                subscriptions={},
                pending_messages={},
                timestamp=datetime.now()
            )
        
        return True, session_present

    async def _send_connack(self, writer: asyncio.StreamWriter, success: bool, session_present: bool) -> None:
        """Send CONNACK packet"""
        packet = bytearray([MessageType.CONNACK << 4, 2])  # Fixed header
        packet.append(1 if session_present else 0)  # Connect acknowledge flags
        packet.append(0 if success else 1)  # Connect return code
        writer.write(bytes(packet))
        await writer.drain()
