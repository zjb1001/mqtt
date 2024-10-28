import unittest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.publish import PublishHandler, PublishPacket, MessageType, QoSLevel

class TestPublishPacketCreation(unittest.TestCase):
    """Test suite for PUBLISH packet creation and encoding"""
    
    def test_qos0_packet_creation(self):
        """Test creating a basic QoS 0 PUBLISH packet"""
        packet = PublishPacket(
            topic="test/topic",
            payload=b"test message",
            qos=QoSLevel.AT_MOST_ONCE
        )
        
        self.assertEqual(packet.topic, "test/topic")
        self.assertEqual(packet.payload, b"test message")
        self.assertEqual(packet.qos, QoSLevel.AT_MOST_ONCE)
        self.assertFalse(packet.retain)
        self.assertFalse(packet.dup)
        self.assertIsNone(packet.packet_id)

    def test_qos1_packet_creation(self):
        """Test creating a QoS 1 PUBLISH packet with packet ID"""
        packet = PublishPacket(
            topic="test/topic",
            payload=b"test message",
            qos=QoSLevel.AT_LEAST_ONCE,
            packet_id=1
        )
        
        self.assertEqual(packet.qos, QoSLevel.AT_LEAST_ONCE)
        self.assertEqual(packet.packet_id, 1)

    def test_retained_packet_creation(self):
        """Test creating a retained PUBLISH packet"""
        packet = PublishPacket(
            topic="test/topic",
            payload=b"test message",
            retain=True
        )
        
        self.assertTrue(packet.retain)

    def test_packet_encoding(self):
        """Test PUBLISH packet encoding"""
        packet = PublishPacket(
            topic="test/topic",
            payload=b"test message",
            qos=QoSLevel.AT_LEAST_ONCE,
            packet_id=1
        )
        
        encoded = packet.encode()
        self.assertIsInstance(encoded, bytes)
        self.assertGreater(len(encoded), 0)
        
        # Check fixed header
        self.assertEqual(encoded[0] >> 4, MessageType.PUBLISH)
        self.assertEqual((encoded[0] & 0x06) >> 1, QoSLevel.AT_LEAST_ONCE)  # QoS bits

    def test_duplicate_packet_creation(self):
        """Test creating a duplicate packet with DUP flag"""
        packet = PublishPacket(
            topic="test/topic",
            payload=b"test message",
            qos=QoSLevel.EXACTLY_ONCE,
            packet_id=1,
            dup=True
        )
        
        self.assertTrue(packet.dup)
        encoded = packet.encode()
        self.assertTrue(encoded[0] & 0x08)  # DUP flag set

class TestQoSMechanics(unittest.IsolatedAsyncioTestCase):
    """Test suite for QoS handling mechanics"""
    
    async def asyncSetUp(self):
        """Set up test fixtures before each test method"""
        self.publish_handler = PublishHandler()

    async def test_qos0_publish(self):
        """Test QoS 0 publish - no packet ID or tracking"""
        packet_id = await self.publish_handler.publish_message(
            topic="test/topic",
            payload=b"test message",
            qos=QoSLevel.AT_MOST_ONCE
        )
        
        self.assertIsNone(packet_id)
        self.assertEqual(len(self.publish_handler.pending_qos_messages), 0)

    async def test_qos1_publish(self):
        """Test QoS 1 publish - packet ID and tracking"""
        packet_id = await self.publish_handler.publish_message(
            topic="test/topic",
            payload=b"test message",
            qos=QoSLevel.AT_LEAST_ONCE
        )
        
        self.assertIsNotNone(packet_id)
        self.assertIn(packet_id, self.publish_handler.pending_qos_messages)
        self.assertEqual(
            self.publish_handler.pending_qos_messages[packet_id].qos_level,
            QoSLevel.AT_LEAST_ONCE
        )

    async def test_qos2_publish(self):
        """Test QoS 2 publish - packet ID and state tracking"""
        packet_id = await self.publish_handler.publish_message(
            topic="test/topic",
            payload=b"test message",
            qos=QoSLevel.EXACTLY_ONCE
        )
        
        self.assertIsNotNone(packet_id)
        self.assertIn(packet_id, self.publish_handler.pending_qos_messages)
        self.assertEqual(
            self.publish_handler.pending_qos_messages[packet_id].qos_level,
            QoSLevel.EXACTLY_ONCE
        )
        self.assertEqual(
            self.publish_handler.pending_qos_messages[packet_id].state,
            "PENDING"
        )

    async def test_packet_id_generation(self):
        """Test unique packet ID generation for QoS > 0"""
        packet_ids = set()
        for _ in range(5):
            packet_id = await self.publish_handler.publish_message(
                topic="test/topic",
                payload=b"test message",
                qos=QoSLevel.AT_LEAST_ONCE
            )
            self.assertNotIn(packet_id, packet_ids)
            packet_ids.add(packet_id)

    async def test_qos2_state_transitions(self):
        """Test QoS 2 state transitions"""
        packet_id = await self.publish_handler.publish_message(
            topic="test/topic",
            payload=b"test message",
            qos=QoSLevel.EXACTLY_ONCE
        )
        
        # PUBREC received
        await self.publish_handler.handle_pubrec(packet_id)
        self.assertEqual(
            self.publish_handler.pending_qos_messages[packet_id].state,
            "PUBREC_RECEIVED"
        )
        
        # PUBCOMP received
        await self.publish_handler.handle_pubcomp(packet_id)
        self.assertNotIn(packet_id, self.publish_handler.pending_qos_messages)

class TestDeliveryTracking(unittest.IsolatedAsyncioTestCase):
    """Test suite for message delivery tracking"""
    
    async def asyncSetUp(self):
        self.publish_handler = PublishHandler()

    async def test_qos1_acknowledgment(self):
        """Test QoS 1 message acknowledgment"""
        packet_id = await self.publish_handler.publish_message(
            topic="test/topic",
            payload=b"test message",
            qos=QoSLevel.AT_LEAST_ONCE
        )
        
        await self.publish_handler.handle_puback(packet_id)
        self.assertNotIn(packet_id, self.publish_handler.pending_qos_messages)

    async def test_retry_mechanism(self):
        """Test message retry mechanism"""
        # Patch asyncio.sleep to speed up test
        with patch('asyncio.sleep', return_value=None):
            packet_id = await self.publish_handler.publish_message(
                topic="test/topic",
                payload=b"test message",
                qos=QoSLevel.AT_LEAST_ONCE
            )
            
            # Wait for retries to complete
            await asyncio.sleep(0.1)
            
            msg = self.publish_handler.pending_qos_messages[packet_id]
            self.assertEqual(msg.retry_count, self.publish_handler.max_retries)

    async def test_message_expiry(self):
        """Test message expiry after max retries"""
        # Patch asyncio.sleep to speed up test
        with patch('asyncio.sleep', return_value=None):
            packet_id = await self.publish_handler.publish_message(
                topic="test/topic",
                payload=b"test message",
                qos=QoSLevel.AT_LEAST_ONCE
            )
            
            # Wait for retries and expiry
            await asyncio.sleep(0.1)
            
            # Message should be removed after max retries
            self.assertNotIn(packet_id, self.publish_handler.pending_qos_messages)

    async def test_concurrent_message_tracking(self):
        """Test tracking multiple messages concurrently"""
        messages = []
        for i in range(5):
            packet_id = await self.publish_handler.publish_message(
                topic=f"test/topic/{i}",
                payload=f"message {i}".encode(),
                qos=QoSLevel.AT_LEAST_ONCE
            )
            messages.append(packet_id)
        
        self.assertEqual(len(self.publish_handler.pending_qos_messages), 5)
        
        # Acknowledge each message
        for packet_id in messages:
            await self.publish_handler.handle_puback(packet_id)
        
        self.assertEqual(len(self.publish_handler.pending_qos_messages), 0)

    async def test_duplicate_acknowledgment(self):
        """Test handling duplicate acknowledgments"""
        packet_id = await self.publish_handler.publish_message(
            topic="test/topic",
            payload=b"test message",
            qos=QoSLevel.AT_LEAST_ONCE
        )
        
        # First acknowledgment
        await self.publish_handler.handle_puback(packet_id)
        self.assertNotIn(packet_id, self.publish_handler.pending_qos_messages)
        
        # Duplicate acknowledgment should not raise error
        await self.publish_handler.handle_puback(packet_id)

if __name__ == '__main__':
    unittest.main()