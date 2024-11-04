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
from src.publish import PublishPacket
from src.connection import ConnectPacket

class TestMessageFlowIntegration(unittest.TestCase):
    """Integration test suite for MQTT message flow scenarios"""

    def setUp(self):
        """Set up test environment before each test"""
        self.message_handler = MessageHandler()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Initialize publish handler and subscriptions handler
        self.message_handler.publish_handler = PublishHandler()
        self.message_handler.subscription_handler = SubscriptionHandler()
        
        # Start message handler
        self.loop.run_until_complete(self.message_handler.start())

    def tearDown(self):
        """Clean up after each test"""
        self.loop.close()

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

    def test_mixed_qos_levels(self):
        """Test message flow with mixed QoS levels"""
        # Set up test data
        publisher_id = "publisher"
        subscriber_qos0_id = "sub_qos0"
        subscriber_qos1_id = "sub_qos1"
        subscriber_qos2_id = "sub_qos2"
        test_topic = "test/topic"

        # Create sessions with different QoS levels
        self.message_handler.sessions = {
            publisher_id: SessionState(
                client_id=publisher_id,
                clean_session=True,
                subscriptions={},
                pending_messages={},
                timestamp=datetime.now()
            ),
            subscriber_qos0_id: SessionState(
                client_id=subscriber_qos0_id,
                clean_session=True,
                subscriptions={test_topic: QoSLevel.AT_MOST_ONCE},
                pending_messages={},
                timestamp=datetime.now()
            ),
            subscriber_qos1_id: SessionState(
                client_id=subscriber_qos1_id,
                clean_session=True,
                subscriptions={test_topic: QoSLevel.AT_LEAST_ONCE},
                pending_messages={},
                timestamp=datetime.now()
            ),
            subscriber_qos2_id: SessionState(
                client_id=subscriber_qos2_id,
                clean_session=True,
                subscriptions={test_topic: QoSLevel.EXACTLY_ONCE},
                pending_messages={},
                timestamp=datetime.now()
            )
        }

        # Publish QoS 2 message
        publish_packet = PublishPacket(
            topic=test_topic,
            payload=b"mixed qos test",
            qos=QoSLevel.EXACTLY_ONCE,
            retain=False
        )

        # Mock the publish handler's packet ID generator
        self.message_handler.publish_handler._get_next_packet_id = Mock(return_value=1)
        
        # Execute message flow
        self.loop.run_until_complete(
            self.message_handler._handle_publish(publish_packet)
        )

        # Verify QoS downgrade for QoS 0 subscriber
        qos0_messages = self.message_handler.get_session_messages(subscriber_qos0_id)
        self.assertEqual(len(qos0_messages), 0)  # QoS 0 has no persistence
        
        # Give time for async message processing
        self.loop.run_until_complete(asyncio.sleep(0.1))

        # Verify QoS downgrade for QoS 1 subscriber
        qos1_messages = self.message_handler.get_session_messages(subscriber_qos1_id)
        self.assertEqual(len(qos1_messages), 1, "QoS 1 subscriber should have one pending message")
        first_qos1_message = list(qos1_messages.values())[0]
        self.assertEqual(
            first_qos1_message.qos_level,
            QoSLevel.AT_LEAST_ONCE,
            "QoS 1 message should maintain AT_LEAST_ONCE delivery"
        )

        # Verify QoS maintained for QoS 2 subscriber
        qos2_messages = self.message_handler.get_session_messages(subscriber_qos2_id)
        self.assertEqual(len(qos2_messages), 1, "QoS 2 subscriber should have one pending message")
        first_qos2_message = list(qos2_messages.values())[0]
        self.assertEqual(
            first_qos2_message.qos_level,
            QoSLevel.EXACTLY_ONCE,
            "QoS 2 message should maintain EXACTLY_ONCE delivery"
        )

        # Verify message content
        for messages in [qos1_messages, qos2_messages]:
            msg = list(messages.values())[0]
            self.assertEqual(msg.topic, test_topic, "Message topic should match")
            self.assertEqual(msg.payload, b"mixed qos test", "Message payload should match")

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