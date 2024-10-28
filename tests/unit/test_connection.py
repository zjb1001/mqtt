import unittest
import asyncio
from unittest.mock import Mock, patch
from datetime import datetime

from src.connection import (
    ConnectionHandler,
    ConnectPacket,
    MessageType,
    FixedHeader,
    ConnectFlags
)
from src.will_message import WillMessage, QoSLevel
from src.session import SessionState

class TestConnectPacketEncodingDecoding(unittest.TestCase):
    """Test suite for CONNECT packet encoding/decoding"""
    
    def setUp(self):
        self.connection_handler = ConnectionHandler()
        self.connect_packet = ConnectPacket(
            client_id="test_client",
            clean_session=True,
            keep_alive=60
        )

    def test_encode_minimal_connect_packet(self):
        """Test encoding of a minimal CONNECT packet with only required fields"""
        encoded = self.connect_packet.encode()
        
        # Verify fixed header
        self.assertEqual(encoded[0] >> 4, MessageType.CONNECT)
        # Verify remaining length
        self.assertEqual(encoded[1], len(encoded) - 2)
        # Verify protocol name and level
        self.assertEqual(encoded[2:8], b'\x00\x04MQTT\x04')
        # Verify connect flags (only clean session set)
        self.assertEqual(encoded[8], 0x02)
        # Verify keep alive
        self.assertEqual(encoded[9:11], b'\x00\x3C')  # 60 seconds
        # Verify client ID
        self.assertEqual(encoded[11:13], b'\x00\x0B')  # Length 11
        self.assertEqual(encoded[13:24], b'test_client')

    def test_encode_full_connect_packet(self):
        """Test encoding of a CONNECT packet with all optional fields"""
        will_message = WillMessage(
            topic="will/topic",
            payload=b"offline",
            qos=QoSLevel.AT_LEAST_ONCE,
            retain=True
        )
        packet = ConnectPacket(
            client_id="test_client",
            clean_session=True,
            keep_alive=60,
            username="user",
            password=b"pass",
            will_message=will_message
        )
        
        encoded = packet.encode()
        # Verify connect flags (all flags set)
        self.assertTrue(encoded[8] & 0x80)  # Username flag
        self.assertTrue(encoded[8] & 0x40)  # Password flag
        self.assertTrue(encoded[8] & 0x04)  # Will flag
        self.assertTrue(encoded[8] & 0x20)  # Will retain
        self.assertEqual((encoded[8] >> 3) & 0x03, QoSLevel.AT_LEAST_ONCE)  # Will QoS

    def test_decode_connect_packet(self):
        """Test decoding of a CONNECT packet"""
        # Create sample packet bytes
        packet_bytes = (
            b'\x00\x04MQTT\x04'  # Protocol name and level
            b'\x02'              # Connect flags (clean session)
            b'\x00\x3C'          # Keep alive 60s
            b'\x00\x0B'          # Client ID length
            b'test_client'       # Client ID
        )
        
        decoded = self.connection_handler._decode_connect_packet(packet_bytes)
        
        self.assertEqual(decoded.client_id, "test_client")
        self.assertTrue(decoded.clean_session)
        self.assertEqual(decoded.keep_alive, 60)
        self.assertIsNone(decoded.username)
        self.assertIsNone(decoded.password)
        self.assertIsNone(decoded.will_message)

class TestConnectionEstablishment(unittest.IsolatedAsyncioTestCase):
    """Test suite for connection establishment"""
    
    async def asyncSetUp(self):
        self.connection_handler = ConnectionHandler()
        self.connect_packet = ConnectPacket(
            client_id="test_client",
            clean_session=True,
            keep_alive=60
        )

    async def test_new_client_connection(self):
        """Test establishing a new client connection"""
        mock_writer = Mock(spec=asyncio.StreamWriter)
        
        success, session_present = await self.connection_handler._process_connect(
            self.connect_packet, mock_writer
        )
        
        self.assertTrue(success)
        self.assertFalse(session_present)
        self.assertIn(self.connect_packet.client_id, self.connection_handler.connections)
        self.assertIn(self.connect_packet.client_id, self.connection_handler.session_states)

    async def test_existing_client_reconnection(self):
        """Test reconnection of an existing client"""
        # Setup existing connection
        old_writer = Mock(spec=asyncio.StreamWriter)
        self.connection_handler.connections["test_client"] = old_writer
        self.connection_handler.session_states["test_client"] = SessionState(
            client_id="test_client",
            clean_session=False,
            subscriptions={},
            pending_messages={},
            timestamp=datetime.now()
        )
        
        # New connection attempt
        new_writer = Mock(spec=asyncio.StreamWriter)
        packet = ConnectPacket(
            client_id="test_client",
            clean_session=False
        )
        
        success, session_present = await self.connection_handler._process_connect(
            packet, new_writer
        )
        
        self.assertTrue(success)
        self.assertTrue(session_present)
        old_writer.close.assert_called_once()
        self.assertEqual(self.connection_handler.connections["test_client"], new_writer)

class TestErrorHandling(unittest.IsolatedAsyncioTestCase):
    """Test suite for error handling"""
    
    async def asyncSetUp(self):
        self.connection_handler = ConnectionHandler()

    async def test_invalid_first_byte(self):
        """Test handling of invalid first byte in connection"""
        mock_reader = Mock(spec=asyncio.StreamReader)
        mock_writer = Mock(spec=asyncio.StreamWriter)
        
        # Simulate invalid first byte
        mock_reader.read.return_value = b'\x20'  # Not CONNECT packet type
        
        await self.connection_handler.handle_new_connection(mock_reader, mock_writer)
        
        mock_writer.close.assert_called_once()

    async def test_malformed_packet(self):
        """Test handling of malformed CONNECT packet"""
        mock_reader = Mock(spec=asyncio.StreamReader)
        mock_writer = Mock(spec=asyncio.StreamWriter)
        
        # Simulate valid first byte but malformed remaining packet
        mock_reader.read.side_effect = [
            b'\x10',  # CONNECT packet type
            b'\x00',  # Zero remaining length (invalid)
        ]
        
        await self.connection_handler.handle_new_connection(mock_reader, mock_writer)
        
        mock_writer.close.assert_called_once()

    async def test_protocol_error(self):
        """Test handling of protocol-level errors"""
        mock_reader = Mock(spec=asyncio.StreamReader)
        mock_writer = Mock(spec=asyncio.StreamWriter)
        
        # Simulate protocol error during packet reading
        mock_reader.read.side_effect = Exception("Protocol error")
        
        await self.connection_handler.handle_new_connection(mock_reader, mock_writer)
        
        mock_writer.close.assert_called_once()

def run_tests():
    """Run connection test suites"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes to suite
    suite.addTests(loader.loadTestsFromTestCase(TestConnectPacketEncodingDecoding))
    suite.addTests(loader.loadTestsFromTestCase(TestConnectionEstablishment))
    suite.addTests(loader.loadTestsFromTestCase(TestErrorHandling))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite).wasSuccessful()

if __name__ == '__main__':
    import sys
    import os
    
    # Add upper level paths
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(os.path.dirname(current_dir))
    grandparent_dir = os.path.dirname(parent_dir)
    sys.path.extend([parent_dir, grandparent_dir])
    
    sys.exit(not run_tests())