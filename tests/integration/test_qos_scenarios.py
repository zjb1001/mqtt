import unittest
import asyncio
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

# Add src into path
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.publish import PublishPacket, PublishHandler
from src.message_handler import MessageHandler, MessageQueue
from src.session import SessionState, QoSMessage
from src.will_message import QoSLevel
from src.connection import ConnectionHandler

class TestQoSScenarios(unittest.TestCase):
    """Integration test suite for MQTT QoS scenarios"""

    async def setUp(self):
        """Set up test environment before each test asynchronously"""
        self.message_handler = MessageHandler()
        self.publish_handler = PublishHandler()
        self.connection_handler = ConnectionHandler()
        
        # Set up test clients
        self.client1_id = "test_publisher"
        self.client2_id = "test_subscriber"
        
        # Create mock connections
        self.client1_writer = Mock()
        self.client2_writer = Mock()
        self.connection_handler.connections = {
            self.client1_id: self.client1_writer,
            self.client2_id: self.client2_writer
        }
        
        # Create test sessions
        self.session1 = SessionState(
            client_id=self.client1_id,
            clean_session=True,
            subscriptions={},
            pending_messages={},
            timestamp=datetime.now()
        )
        self.session2 = SessionState(
            client_id=self.client2_id,
            clean_session=True,
            subscriptions={"test/topic": QoSLevel.EXACTLY_ONCE},
            pending_messages={},
            timestamp=datetime.now()
        )
        
        self.message_handler.sessions = {
            self.client1_id: self.session1,
            self.client2_id: self.session2
        }

    async def tearDown(self):
        """Clean up after each test asynchronously"""
        # Clean up any pending tasks
        tasks = asyncio.all_tasks()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def test_qos0_delivery_pattern(self):
        """Test QoS 0 message delivery patterns"""
        # Create QoS 0 message
        publish_packet = PublishPacket(
            topic="test/topic",
            payload=b"QoS 0 test message",
            qos=QoSLevel.AT_MOST_ONCE,
            retain=False
        )
        
        # Process message
        await self.message_handler._handle_publish(publish_packet)
        
        # Verify delivery behavior
        self.client2_writer.write.assert_called_once()
        self.assertEqual(len(self.session2.pending_messages), 0)
        
        # Verify no retransmission attempts
        self.client2_writer.write.reset_mock()
        await asyncio.sleep(0.1)
        self.client2_writer.write.assert_not_called()

    async def test_qos1_acknowledgment_flow(self):
        """Test QoS 1 message delivery and acknowledgment flow"""
        # Create QoS 1 message
        publish_packet = PublishPacket(
            topic="test/topic",
            payload=b"QoS 1 test message",
            qos=QoSLevel.AT_LEAST_ONCE,
            retain=False,
            packet_id=1
        )
        
        # Process initial message
        await self.message_handler._handle_publish(publish_packet)
        
        # Verify message is stored in session
        self.assertIn(1, self.session2.pending_messages)
        qos_msg = self.session2.pending_messages[1]
        self.assertEqual(qos_msg.qos_level, QoSLevel.AT_LEAST_ONCE)
        
        # Simulate PUBACK receipt
        await self.message_handler.handle_message_acknowledgment(
            self.client2_id, 1, "PUBACK"
        )
        
        # Verify message is removed after acknowledgment
        self.assertNotIn(1, self.session2.pending_messages)

    async def test_qos1_retry_behavior(self):
        """Test QoS 1 message retry behavior"""
        # Configure shorter retry interval for testing
        self.message_handler.retry_interval = 0.1
        
        # Create QoS 1 message
        publish_packet = PublishPacket(
            topic="test/topic",
            payload=b"QoS 1 retry test",
            qos=QoSLevel.AT_LEAST_ONCE,
            retain=False,
            packet_id=1
        )
        
        # Process message
        await self.message_handler._handle_publish(publish_packet)
        
        # Wait briefly for message to be stored
        await asyncio.sleep(0.1)
        
        # Verify message is stored
        self.assertIn(1, self.session2.pending_messages)
        qos_msg = self.session2.pending_messages[1]
        self.assertFalse(qos_msg.ack_received)
        
        # Wait for retry attempt
        await asyncio.sleep(0.2)
        
        # Verify retry occurred
        qos_msg = self.session2.pending_messages[1]
        self.assertTrue(qos_msg.retry_count > 0)
        
        # Simulate late PUBACK
        await self.message_handler.handle_message_acknowledgment(
            self.client2_id, 1, "PUBACK"
        )
        
        # Verify message is acknowledged
        self.assertNotIn(1, self.session2.pending_messages)

    async def test_qos2_complete_flow(self):
        """Test complete QoS 2 message flow"""
            # Create QoS 2 message
            publish_packet = PublishPacket(
                topic="test/topic",
                payload=b"QoS 2 test message",
                qos=QoSLevel.EXACTLY_ONCE,
                retain=False,
                packet_id=1
            )
            
            # Process initial message
            await self.message_handler._handle_publish(publish_packet)
            
            # Verify message is stored
            self.assertIn(1, self.session2.pending_messages)
            qos_msg = self.session2.pending_messages[1]
            self.assertEqual(qos_msg.state, "PENDING")
            
            # Simulate PUBREC
            await self.message_handler.handle_message_acknowledgment(
                self.client2_id, 1, "PUBREC"
            )
            self.assertEqual(qos_msg.state, "PUBREC_RECEIVED")
            
            # Simulate PUBREL
            await self.message_handler.handle_message_acknowledgment(
                self.client2_id, 1, "PUBREL"
            )
            self.assertEqual(qos_msg.state, "PUBREL_RECEIVED")
            
            # Simulate PUBCOMP
            await self.message_handler.handle_message_acknowledgment(
                self.client2_id, 1, "PUBCOMP"
            )
            
            # Verify message is completed
            self.assertNotIn(1, self.session2.pending_messages)


    async def test_qos2_partial_flow(self):
        """Test QoS 2 partial completion scenarios"""
            # Set shorter retry interval
            self.message_handler.retry_interval = 0.1
            
            # Create QoS 2 message
            publish_packet = PublishPacket(
                topic="test/topic",
                payload=b"QoS 2 partial test",
                qos=QoSLevel.EXACTLY_ONCE,
                retain=False,
                packet_id=1
            )
            
            # Process initial message
            await self.message_handler._handle_publish(publish_packet)
            
            # Simulate PUBREC
            await self.message_handler.handle_message_acknowledgment(
                self.client2_id, 1, "PUBREC"
            )
            
            # Wait for retry attempt
            await asyncio.sleep(0.2)
            
            # Verify message is still in PUBREC state
            qos_msg = self.session2.pending_messages[1]
            self.assertEqual(qos_msg.state, "PUBREC_RECEIVED")
            self.assertTrue(qos_msg.retry_count > 0)
            
            # Complete the flow
            await self.message_handler.handle_message_acknowledgment(
                self.client2_id, 1, "PUBREL"
            )
            await self.message_handler.handle_message_acknowledgment(
                self.client2_id, 1, "PUBCOMP"
            )
            
            # Verify message is completed
            self.assertNotIn(1, self.session2.pending_messages)
            
        self.loop.run_until_complete(run_test())

    async def test_qos2_recovery_procedure(self):
        """Test QoS 2 recovery procedures"""
            # Create QoS 2 message in PUBREC state
            qos_msg = QoSMessage(
                message_id=1,
                qos_level=QoSLevel.EXACTLY_ONCE,
                timestamp=datetime.now()
            )
            qos_msg.state = "PUBREC_RECEIVED"
            self.session2.pending_messages[1] = qos_msg
            
            # Simulate connection loss and recovery
            publish_packet = PublishPacket(
                topic="test/topic",
                payload=b"QoS 2 recovery test",
                qos=QoSLevel.EXACTLY_ONCE,
                retain=False,
                packet_id=1,
                dup=True
            )
            
            # Process duplicate message
            await self.message_handler._handle_publish(publish_packet)
            
            # Verify message state is preserved
            self.assertIn(1, self.session2.pending_messages)
            recovered_msg = self.session2.pending_messages[1]
            self.assertEqual(recovered_msg.state, "PUBREC_RECEIVED")
            
            # Complete the flow
            await self.message_handler.handle_message_acknowledgment(
                self.client2_id, 1, "PUBREL"
            )
            await self.message_handler.handle_message_acknowledgment(
                self.client2_id, 1, "PUBCOMP"
            )
            
            # Verify message is completed
            self.assertNotIn(1, self.session2.pending_messages)
            
        self.loop.run_until_complete(run_test())

    async def test_mixed_qos_levels(self):
        """Test handling of mixed QoS level messages"""
            # Create messages with different QoS levels
            messages = [
                PublishPacket(
                    topic="test/topic",
                    payload=b"QoS 0 message",
                    qos=QoSLevel.AT_MOST_ONCE,
                    retain=False
                ),
                PublishPacket(
                    topic="test/topic",
                    payload=b"QoS 1 message",
                    qos=QoSLevel.AT_LEAST_ONCE,
                    retain=False,
                    packet_id=1
                ),
                PublishPacket(
                    topic="test/topic",
                    payload=b"QoS 2 message",
                    qos=QoSLevel.EXACTLY_ONCE,
                    retain=False,
                    packet_id=2
                )
            ]
            
            # Process all messages
            for packet in messages:
                await self.message_handler._handle_publish(packet)
            
            # Verify QoS 0 message is not stored
            self.assertNotIn(0, self.session2.pending_messages)
            
            # Verify QoS 1 and 2 messages are stored
            self.assertIn(1, self.session2.pending_messages)
            self.assertIn(2, self.session2.pending_messages)
            
            # Complete QoS 1 flow
            await self.message_handler.handle_message_acknowledgment(
                self.client2_id, 1, "PUBACK"
            )
            
            # Complete QoS 2 flow
            await self.message_handler.handle_message_acknowledgment(
                self.client2_id, 2, "PUBREC"
            )
            await self.message_handler.handle_message_acknowledgment(
                self.client2_id, 2, "PUBREL"
            )
            await self.message_handler.handle_message_acknowledgment(
                self.client2_id, 2, "PUBCOMP"
            )
            
            # Verify all messages are completed
            self.assertEqual(len(self.session2.pending_messages), 0)
            
        self.loop.run_until_complete(run_test())

async def run_tests():
    """Run all QoS scenario tests"""
    test_cases = [
        TestQoSScenarios("test_qos0_delivery_pattern"),
        TestQoSScenarios("test_qos1_acknowledgment_flow"),
        TestQoSScenarios("test_qos1_retry_behavior"),
        TestQoSScenarios("test_qos2_complete_flow"),
        TestQoSScenarios("test_qos2_partial_flow"),
        TestQoSScenarios("test_qos2_recovery_procedure"),
        TestQoSScenarios("test_mixed_qos_levels")
    ]
    
    for test_case in test_cases:
        await test_case.setUp()
        try:
            test_method = getattr(test_case, test_case._testMethodName)
            await test_method()
        finally:
            await test_case.tearDown()

def run_test():
    """Create and run the test suite"""
    asyncio.run(run_tests())

if __name__ == '__main__':
    run_test()