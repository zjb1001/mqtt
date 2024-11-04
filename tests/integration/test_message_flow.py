import unittest
from unittest.mock import Mock, patch
import asyncio
from datetime import datetime

# add src into path, src path upper level two from this file
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.message_handler import MessageHandler, RetainedMessage
from src.session import SessionState, QoSMessage
from src.will_message import QoSLevel
from src.publish import PublishPacket, PublishHandler
from src.connection import ConnectPacket
from src.subscribe import SubscriptionHandler, SubscribePacket

class TestMessageFlowIntegration(unittest.TestCase):
    """Integration test suite for MQTT message flow scenarios"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment once for all tests"""
        cls.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(cls.loop)

    async def asyncSetUp(self):
        """Set up test environment before each test"""
        self.message_handler = MessageHandler()
        
        # Initialize handlers
        self.message_handler.publish_handler = PublishHandler()
        self.message_handler.subscription_handler = SubscriptionHandler()
        
        # Start message handler
        self.message_processing_task = await self.message_handler.start()

    async def asyncTearDown(self):
        """Clean up after each test"""
        # Cancel message processing task
        if hasattr(self, 'message_processing_task'):
            self.message_processing_task.cancel()
            try:
                await self.message_processing_task
            except asyncio.CancelledError:
                pass
            
        # Clear message queue
        while not self.message_handler.message_queue.queue.empty():
            try:
                self.message_handler.message_queue.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def setUp(self):
        self.loop.run_until_complete(self.asyncSetUp())

    def tearDown(self):
        self.loop.run_until_complete(self.asyncTearDown())

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests"""
        pending = asyncio.all_tasks(cls.loop)
        cls.loop.run_until_complete(asyncio.gather(*pending))
        cls.loop.close()

    def test_single_publisher_multiple_subscribers(self):
        """Test end-to-end message flow with one publisher and multiple subscribers"""
        # Set up test data
        publisher_id = "publisher1"
        subscriber1_id = "subscriber1"
        subscriber2_id = "subscriber2"
        test_topic = "test/topic"
        test_payload = b"test message"

        # Create sessions
        self.message_handler.sessions = {
            publisher_id: SessionState(
                client_id=publisher_id,
                clean_session=True,
                subscriptions={},
                pending_messages={},
                timestamp=datetime.now()
            ),
            subscriber1_id: SessionState(
                client_id=subscriber1_id,
                clean_session=True,
                subscriptions={test_topic: QoSLevel.AT_LEAST_ONCE},
                pending_messages={},
                timestamp=datetime.now()
            ),
            subscriber2_id: SessionState(
                client_id=subscriber2_id,
                clean_session=True,
                subscriptions={test_topic: QoSLevel.AT_MOST_ONCE},
                pending_messages={},
                timestamp=datetime.now()
            )
        }

        # Create publish packet
        publish_packet = PublishPacket(
            topic=test_topic,
            payload=test_payload,
            qos=QoSLevel.AT_LEAST_ONCE,
            retain=False
        )

        # Execute message flow
        self.loop.run_until_complete(
            self.message_handler._handle_publish(publish_packet)
        )

        # Verify message delivery
        self.assertIn(subscriber1_id, self.message_handler.sessions)
        self.assertIn(subscriber2_id, self.message_handler.sessions)
        
        # Check QoS 1 subscriber has pending message
        subscriber1_messages = self.message_handler.get_session_messages(subscriber1_id)
        self.assertEqual(len(subscriber1_messages), 1)
        
        # Check QoS 0 subscriber has no pending messages
        subscriber2_messages = self.message_handler.get_session_messages(subscriber2_id)
        self.assertEqual(len(subscriber2_messages), 0)

    def test_multiple_publishers_single_subscriber(self):
        """Test message flow with multiple publishers and one subscriber"""
        # Set up test data
        publisher1_id = "publisher1"
        publisher2_id = "publisher2"
        subscriber_id = "subscriber1"
        test_topic = "test/topic"

        # Create sessions
        self.message_handler.sessions = {
            publisher1_id: SessionState(
                client_id=publisher1_id,
                clean_session=True,
                subscriptions={},
                pending_messages={},
                timestamp=datetime.now()
            ),
            publisher2_id: SessionState(
                client_id=publisher2_id,
                clean_session=True,
                subscriptions={},
                pending_messages={},
                timestamp=datetime.now()
            ),
            subscriber_id: SessionState(
                client_id=subscriber_id,
                clean_session=True,
                subscriptions={test_topic: QoSLevel.EXACTLY_ONCE},
                pending_messages={},
                timestamp=datetime.now()
            )
        }

        # Create publish packets
        publish_packet1 = PublishPacket(
            topic=test_topic,
            payload=b"message1",
            qos=QoSLevel.EXACTLY_ONCE,
            retain=False
        )
        
        publish_packet2 = PublishPacket(
            topic=test_topic,
            payload=b"message2",
            qos=QoSLevel.AT_LEAST_ONCE,
            retain=False
        )

        # Execute message flow for both publishers
        self.loop.run_until_complete(asyncio.gather(
            self.message_handler._handle_publish(publish_packet1),
            self.message_handler._handle_publish(publish_packet2)
        ))

        # Verify message delivery
        subscriber_messages = self.message_handler.get_session_messages(subscriber_id)
        self.assertEqual(len(subscriber_messages), 2)

        # Verify QoS levels are preserved
        qos_levels = {msg.qos_level for msg in subscriber_messages.values()}
        self.assertEqual(qos_levels, {QoSLevel.EXACTLY_ONCE, QoSLevel.AT_LEAST_ONCE})

    def test_session_persistence_and_message_delivery(self):
        """Test session persistence and message delivery after reconnection"""
        # Set up test data
        client_id = "persistent_client"
        test_topic = "test/topic"

        # Create initial session
        initial_session = SessionState(
            client_id=client_id,
            clean_session=False,
            subscriptions={test_topic: QoSLevel.AT_LEAST_ONCE},
            pending_messages={},
            timestamp=datetime.now()
        )
        self.message_handler.sessions[client_id] = initial_session

        # Publish message while client is "offline"
        publish_packet = PublishPacket(
            topic=test_topic,
            payload=b"offline message",
            qos=QoSLevel.AT_LEAST_ONCE,
            retain=False
        )

        self.loop.run_until_complete(
            self.message_handler._handle_publish(publish_packet)
        )

        # Simulate client reconnection
        connect_packet = ConnectPacket(
            client_id=client_id,
            clean_session=False
        )

        # Verify session persistence
        self.assertIn(client_id, self.message_handler.sessions)
        persistent_session = self.message_handler.sessions[client_id]
        
        # Verify subscriptions maintained
        self.assertIn(test_topic, persistent_session.subscriptions)
        self.assertEqual(
            persistent_session.subscriptions[test_topic],
            QoSLevel.AT_LEAST_ONCE
        )

        # Verify pending messages maintained
        pending_messages = self.message_handler.get_session_messages(client_id)
        self.assertEqual(len(pending_messages), 1)

    async def test_mixed_qos_levels(self):
        """Test message delivery with different QoS level combinations"""
        # Set up subscribers with different QoS levels
        client1 = "client1"
        client2 = "client2"
        topic = "test/topic"
        
        # Create sessions
        self.message_handler.sessions[client1] = SessionState(
            client_id=client1,
            clean_session=True,
            subscriptions={topic: QoSLevel.AT_LEAST_ONCE},
            pending_messages={},
            timestamp=datetime.now()
        )
        self.message_handler.sessions[client2] = SessionState(
            client_id=client2,
            clean_session=True, 
            subscriptions={topic: QoSLevel.AT_MOST_ONCE},
            pending_messages={},
            timestamp=datetime.now()
        )

        # Subscribe clients
        sub_packet1 = SubscribePacket(1, [(topic, QoSLevel.AT_LEAST_ONCE)])
        sub_packet2 = SubscribePacket(2, [(topic, QoSLevel.AT_MOST_ONCE)])
        
        await self.message_handler.subscription_handler.handle_subscribe(client1, sub_packet1)
        await self.message_handler.subscription_handler.handle_subscribe(client2, sub_packet2)

        # Publish QoS 2 message
        publish_packet = PublishPacket(
            topic=topic,
            payload=b"test message",
            qos=QoSLevel.EXACTLY_ONCE,
            retain=False,
            packet_id=1
        )
        
        await self.message_handler._handle_publish(publish_packet)
        
        # Verify QoS handling
        await asyncio.sleep(0.1)  # Allow async processing
        
        # Client1 (QoS 1) should have pending message
        self.assertEqual(len(self.message_handler.sessions[client1].pending_messages), 1)
        
        # Client2 (QoS 0) should not have pending message
        self.assertEqual(len(self.message_handler.sessions[client2].pending_messages), 0)

if __name__ == '__main__':
    # Create a test suite combining all test cases
    suite = unittest.TestSuite()

    # suite.addTest(TestMessageFlowIntegration("test_single_publisher_multiple_subscribers"))
    # suite.addTest(TestMessageFlowIntegration("test_multiple_publishers_single_subscriber"))
    # suite.addTest(TestMessageFlowIntegration("test_session_persistence_and_message_delivery"))
    suite.addTest(TestMessageFlowIntegration("test_mixed_qos_levels"))

    # Run the test suite
    runner = unittest.TextTestRunner()
    runner.run(suite)