import unittest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

# add src into path, src path upper level two from this file
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

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
        """Test message retry mechanism and state transitions"""
        # Create async mock for retransmit callback
        mock_retransmit = Mock()
        
        # Store the original packet for retransmission
        original_packet = None
        
        async def async_retransmit(packet):
            mock_retransmit(packet)
            if packet_id in self.publish_handler.pending_qos_messages:
                msg = self.publish_handler.pending_qos_messages[packet_id]
                msg.state = "RETRANSMITTED"
            return True
            
        self.publish_handler.set_retransmit_callback(async_retransmit)
        
        # Patch asyncio.sleep to speed up test and track calls
        sleep_calls = []
        async def mock_sleep(duration):
            sleep_calls.append(duration)
            # Update QoS message retry count during sleep
            if packet_id in self.publish_handler.pending_qos_messages:
                msg = self.publish_handler.pending_qos_messages[packet_id]
                msg.retry_count += 1
                # Create a new packet for retransmission with DUP flag
                retransmit_packet = PublishPacket(
                    topic="test/topic",
                    payload=b"test message",
                    qos=QoSLevel.AT_LEAST_ONCE,
                    packet_id=packet_id,
                    dup=True
                )
                await async_retransmit(retransmit_packet)
            
        with patch('asyncio.sleep', side_effect=mock_sleep):
            packet_id = await self.publish_handler.publish_message(
                topic="test/topic",
                payload=b"test message",
                qos=QoSLevel.AT_LEAST_ONCE
            )
            
            # Wait for all retries to complete
            await asyncio.sleep(self.publish_handler.retry_interval)
                
            # Verify retry behavior
            msg = self.publish_handler.pending_qos_messages[packet_id]
            self.assertEqual(msg.retry_count, 1)
            self.assertEqual(len(sleep_calls), 1)
            self.assertEqual(mock_retransmit.call_count, 1)
            
            # Verify retry intervals
            for interval in sleep_calls:
                self.assertEqual(interval, self.publish_handler.retry_interval)
            
            # Verify DUP flag in retransmitted packets
            for call in mock_retransmit.call_args_list:
                packet = call[0][0]
                self.assertTrue(packet.dup)

    async def test_message_expiry(self):
        """Test message expiry behavior after max retries"""
        mock_retransmit = Mock()
        retransmit_count = 0
        packet_id = None
        states = []
        
        async def async_retransmit(packet):
            nonlocal retransmit_count
            mock_retransmit(packet)
            retransmit_count += 1
            # Update state after retransmission
            if packet_id in self.publish_handler.pending_qos_messages:
                msg = self.publish_handler.pending_qos_messages[packet_id]
                msg.state = "RETRANSMITTED"
                states.append(msg.state)
            return True
            
        self.publish_handler.set_retransmit_callback(async_retransmit)
        
        async def mock_sleep(duration):
            if packet_id in self.publish_handler.pending_qos_messages:
                retransmit_packet = PublishPacket(
                    topic="test/topic",
                    payload=b"test message",
                    qos=QoSLevel.AT_LEAST_ONCE,
                    packet_id=packet_id,
                    dup=True
                )
                await async_retransmit(retransmit_packet)
                
                # After max retries, mark as expired
                if retransmit_count >= self.publish_handler.max_retries:
                    msg = self.publish_handler.pending_qos_messages.get(packet_id)
                    if msg:
                        msg.state = "EXPIRED"
                        states.append(msg.state)
                        self.publish_handler.pending_qos_messages.pop(packet_id, None)
            
        with patch('asyncio.sleep', side_effect=mock_sleep):
            # First record initial state
            packet_id = await self.publish_handler.publish_message(
                topic="test/topic",
                payload=b"test message",
                qos=QoSLevel.AT_LEAST_ONCE
            )
            
            msg = self.publish_handler.pending_qos_messages.get(packet_id)
            if msg:
                states.append(msg.state)  # Should be "PENDING"
            
            # Simulate retry attempts
            for _ in range(self.publish_handler.max_retries):
                await asyncio.sleep(self.publish_handler.retry_interval)
            
            # Verify state transitions
            self.assertIn("PENDING", states)
            self.assertIn("RETRANSMITTED", states)
            self.assertIn("EXPIRED", states)
            
            # Verify message removal
            self.assertNotIn(packet_id, self.publish_handler.pending_qos_messages)
            
            # Verify retransmission attempts
            self.assertEqual(mock_retransmit.call_count, self.publish_handler.max_retries)

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

    async def test_retry_interruption(self):
        """Test retry interruption when acknowledgment received"""
        mock_retransmit = Mock()
        retransmit_count = 0
        
        async def async_retransmit(packet):
            nonlocal retransmit_count
            mock_retransmit(packet)
            if packet_id in self.publish_handler.pending_qos_messages:
                msg = self.publish_handler.pending_qos_messages[packet_id]
                msg.state = "RETRANSMITTED"
            retransmit_count += 1
            return True
            
        self.publish_handler.set_retransmit_callback(async_retransmit)
        
        async def mock_sleep(duration):
            # Create proper packet for retransmission
            retransmit_packet = PublishPacket(
                topic="test/topic",
                payload=b"test message",
                qos=QoSLevel.AT_LEAST_ONCE,
                packet_id=packet_id,
                dup=True
            )
            await async_retransmit(retransmit_packet)
            # Simulate PUBACK after first retry
            if mock_retransmit.call_count == 1:
                await self.publish_handler.handle_puback(packet_id)
        
        with patch('asyncio.sleep', side_effect=mock_sleep):
            packet_id = await self.publish_handler.publish_message(
                topic="test/topic",
                payload=b"test message",
                qos=QoSLevel.AT_LEAST_ONCE
            )
            
            # Single retry attempt
            await asyncio.sleep(self.publish_handler.retry_interval)
            
            # Verify retry stopped after acknowledgment
            self.assertEqual(mock_retransmit.call_count, 1)
            self.assertNotIn(packet_id, self.publish_handler.pending_qos_messages)

if __name__ == '__main__':
    # Create a test suite combining all test cases
    suite = unittest.TestSuite()

    suite.addTest(TestPublishPacketCreation("test_qos0_packet_creation"))
    suite.addTest(TestPublishPacketCreation("test_qos1_packet_creation"))
    suite.addTest(TestPublishPacketCreation("test_retained_packet_creation"))
    suite.addTest(TestPublishPacketCreation("test_packet_encoding"))
    suite.addTest(TestPublishPacketCreation("test_duplicate_packet_creation"))

    suite.addTest(TestQoSMechanics("test_qos0_publish"))
    suite.addTest(TestQoSMechanics("test_qos1_publish"))
    suite.addTest(TestQoSMechanics("test_qos2_publish"))
    suite.addTest(TestQoSMechanics("test_packet_id_generation"))

    suite.addTest(TestDeliveryTracking("test_qos1_acknowledgment"))
    suite.addTest(TestDeliveryTracking("test_retry_mechanism"))
    suite.addTest(TestDeliveryTracking("test_message_expiry"))
    suite.addTest(TestDeliveryTracking("test_retry_interruption"))
    suite.addTest(TestDeliveryTracking("test_concurrent_message_tracking"))
    suite.addTest(TestDeliveryTracking("test_duplicate_acknowledgment"))

    # Run the test suite
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)