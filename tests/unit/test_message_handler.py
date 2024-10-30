import unittest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta
import asyncio

# add src into path, src path upper level two from this file
import sys
import os
# Add src into path, src path upper level two from this file
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.message_handler import (
    MessageHandler, MessageQueue, Message, 
    RetainedMessage, QoSMessage
)
from src.will_message import QoSLevel
from src.publish import PublishPacket
from src.session import SessionState

class TestMessageQueue(unittest.TestCase):
    """Test suite for MessageQueue functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.message_queue = MessageQueue()
        
    def test_retained_message_storage(self):
        """Test storing and retrieving retained messages"""
        # Create retained message
        retained_msg = RetainedMessage(
            topic="test/topic",
            payload=b"test message",
            qos=QoSLevel.AT_LEAST_ONCE,
            timestamp=datetime.now(),
            last_modified=datetime.now()
        )
        
        # Store message
        self.message_queue.store_retained_message("test/topic", retained_msg)
        
        # Retrieve message
        retrieved_msg = self.message_queue.get_retained_message("test/topic")
        self.assertIsNotNone(retrieved_msg)
        self.assertEqual(retrieved_msg.topic, "test/topic")
        self.assertEqual(retrieved_msg.payload, b"test message")
        self.assertEqual(retrieved_msg.qos, QoSLevel.AT_LEAST_ONCE)
        
        # Test non-existent topic
        missing_msg = self.message_queue.get_retained_message("missing/topic")
        self.assertIsNone(missing_msg)

    def test_inflight_message_tracking(self):
        """Test tracking of inflight QoS messages"""
        # Create QoS message
        qos_msg = QoSMessage(
            message_id=1,
            qos_level=QoSLevel.AT_LEAST_ONCE,
            timestamp=datetime.now()
        )
        
        # Track message
        client_id = "test_client"
        self.message_queue.track_inflight_message(client_id, qos_msg)
        
        # Verify tracking
        self.assertIn(client_id, self.message_queue.inflight_messages)
        self.assertIn(1, self.message_queue.inflight_messages[client_id])
        tracked_msg = self.message_queue.inflight_messages[client_id][1]
        self.assertEqual(tracked_msg.message_id, 1)
        self.assertEqual(tracked_msg.qos_level, QoSLevel.AT_LEAST_ONCE)

    @patch('asyncio.Queue')
    def test_message_queue_operations(self, mock_queue):
        """Test async queue operations"""
        mock_queue_instance = AsyncMock()
        mock_queue.return_value = mock_queue_instance
        
        message_queue = MessageQueue()
        test_message = Message(type=1)
        
        # Test put operation
        asyncio.run(message_queue.put(test_message))
        mock_queue_instance.put.assert_called_once_with(test_message)
        
        # Test get operation
        asyncio.run(message_queue.get())
        mock_queue_instance.get.assert_called_once()

class TestMessageHandler(unittest.TestCase):
    """Test suite for MessageHandler functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.message_handler = MessageHandler()
        
    @patch('src.message_handler.PublishHandler')
    @patch('src.message_handler.SubscriptionHandler')
    def test_publish_message_routing(self, mock_sub_handler, mock_pub_handler):
        """Test routing of publish messages to subscribers"""
        # Setup mocks
        mock_sub_handler.return_value.get_matching_subscribers.return_value = {
            "client1": QoSLevel.AT_LEAST_ONCE,
            "client2": QoSLevel.AT_MOST_ONCE
        }
        mock_pub_handler.return_value._get_next_packet_id.return_value = 1
        
        # Create publish packet
        publish_packet = PublishPacket(
            topic="test/topic",
            payload=b"test message",
            qos=QoSLevel.AT_LEAST_ONCE,
            retain=True,
            packet_id=1
        )
        
        # Create test sessions
        self.message_handler.sessions = {
            "client1": SessionState(
                client_id="client1",
                clean_session=True,
                subscriptions={},
                pending_messages={},
                timestamp=datetime.now()
            ),
            "client2": SessionState(
                client_id="client2",
                clean_session=True,
                subscriptions={},
                pending_messages={},
                timestamp=datetime.now()
            )
        }
        
        # Process publish packet
        asyncio.run(self.message_handler._handle_publish(publish_packet))
        
        # Verify retained message storage
        retained_msg = self.message_handler.message_queue.get_retained_message("test/topic")
        self.assertIsNotNone(retained_msg)
        self.assertEqual(retained_msg.topic, "test/topic")
        self.assertEqual(retained_msg.payload, b"test message")
        
        # Verify QoS message tracking for AT_LEAST_ONCE subscriber
        client1_session = self.message_handler.sessions["client1"]
        self.assertEqual(len(client1_session.pending_messages), 1)
        
        # Verify no QoS tracking for AT_MOST_ONCE subscriber
        client2_session = self.message_handler.sessions["client2"]
        self.assertEqual(len(client2_session.pending_messages), 0)

    @patch('asyncio.sleep')
    async def test_qos_retry_mechanism(self, mock_sleep):
        """Test QoS message retry mechanism"""
        # Setup test data
        client_id = "test_client"
        qos_msg = QoSMessage(
            message_id=1,
            qos_level=QoSLevel.EXACTLY_ONCE,
            timestamp=datetime.now()
        )
        publish_packet = PublishPacket(
            topic="test/topic",
            payload=b"test message",
            qos=QoSLevel.EXACTLY_ONCE,
            retain=False,
            packet_id=1
        )
        
        # Create test session
        self.message_handler.sessions[client_id] = SessionState(
            client_id=client_id,
            clean_session=True,
            subscriptions={},
            pending_messages={1: qos_msg},
            timestamp=datetime.now()
        )
        
        # Test retry mechanism
        await self.message_handler._handle_qos_retry(client_id, qos_msg, publish_packet)
        
        # Verify retry attempts
        self.assertEqual(qos_msg.retry_count, self.message_handler.max_retries)
        self.assertFalse(qos_msg.ack_received)
        mock_sleep.assert_called()

    def test_message_acknowledgment(self):
        """Test handling of message acknowledgments"""
        # Setup test data
        client_id = "test_client"
        qos_msg = QoSMessage(
            message_id=1,
            qos_level=QoSLevel.EXACTLY_ONCE,
            timestamp=datetime.now()
        )
        
        # Create test session with pending message
        self.message_handler.sessions[client_id] = SessionState(
            client_id=client_id,
            clean_session=True,
            subscriptions={},
            pending_messages={1: qos_msg},
            timestamp=datetime.now()
        )
        
        # Test PUBREC acknowledgment
        asyncio.run(self.message_handler.handle_message_acknowledgment(
            client_id, 1, "PUBREC"
        ))
        self.assertEqual(qos_msg.state, "PUBREC_RECEIVED")
        
        # Test PUBREL acknowledgment
        asyncio.run(self.message_handler.handle_message_acknowledgment(
            client_id, 1, "PUBREL"
        ))
        self.assertEqual(qos_msg.state, "PUBREL_RECEIVED")
        
        # Test PUBCOMP acknowledgment
        asyncio.run(self.message_handler.handle_message_acknowledgment(
            client_id, 1, "PUBCOMP"
        ))
        self.assertTrue(qos_msg.ack_received)
        self.assertEqual(qos_msg.state, "COMPLETED")
        
        # Verify message removal
        self.assertEqual(len(self.message_handler.sessions[client_id].pending_messages), 0)

    def test_session_message_retrieval(self):
        """Test retrieving pending messages for a session"""
        # Setup test data
        client_id = "test_client"
        qos_msg = QoSMessage(
            message_id=1,
            qos_level=QoSLevel.AT_LEAST_ONCE,
            timestamp=datetime.now()
        )
        
        # Create test session
        self.message_handler.sessions[client_id] = SessionState(
            client_id=client_id,
            clean_session=True,
            subscriptions={},
            pending_messages={1: qos_msg},
            timestamp=datetime.now()
        )
        
        # Test message retrieval for existing session
        messages = self.message_handler.get_session_messages(client_id)
        self.assertEqual(len(messages), 1)
        self.assertIn(1, messages)
        
        # Test message retrieval for non-existent session
        messages = self.message_handler.get_session_messages("missing_client")
        self.assertEqual(len(messages), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
    # Create a test suite combining all test cases
    suite = unittest.TestSuite()

    suite.addTest(TestMessageQueue("test_retained_message_storage"))
    suite.addTest(TestMessageQueue("test_inflight_message_tracking"))
    suite.addTest(TestMessageQueue("test_message_queue_operations"))

    suite.addTest(TestMessageHandler("test_publish_message_routing"))
    suite.addTest(TestMessageHandler("test_qos_retry_mechanism"))
    suite.addTest(TestMessageHandler("test_message_acknowledgment"))
    suite.addTest(TestMessageHandler("test_session_message_retrieval"))

    # Run the test suite
    runner = unittest.TextTestRunner()
    runner.run(suite)
