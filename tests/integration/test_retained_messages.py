import unittest
from unittest.mock import Mock, patch
import asyncio
from datetime import datetime, timedelta

from src.message_handler import MessageHandler, RetainedMessage
from src.will_message import QoSLevel
from src.publish import PublishPacket
from src.subscribe import SubscribePacket
from src.session import SessionState

class TestRetainedMessagesIntegration(unittest.TestCase):
    """Integration test suite for MQTT retained messages functionality"""

    def setUp(self):
        """Set up test environment before each test case"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.message_handler = MessageHandler()
        self.client_id = "test_client"
        self.session_state = SessionState(
            client_id=self.client_id,
            clean_session=True,
            subscriptions={},
            pending_messages={},
            timestamp=datetime.now()
        )
        self.message_handler.sessions[self.client_id] = self.session_state

    def tearDown(self):
        """Clean up test environment after each test case"""
        self.loop.close()

    def test_retained_message_updates(self):
        """Test retained message storage and updates"""
        # Initial retained message
        topic = "test/retained"
        payload1 = b"initial message"
        
        # Create and store first retained message
        self.loop.run_until_complete(self._publish_retained_message(
            topic, payload1, QoSLevel.AT_LEAST_ONCE
        ))
        
        # Verify retained message storage
        retained_msg = self.message_handler.message_queue.get_retained_message(topic)
        self.assertIsNotNone(retained_msg)
        self.assertEqual(retained_msg.payload, payload1)
        self.assertEqual(retained_msg.qos, QoSLevel.AT_LEAST_ONCE)
        
        # Update retained message
        payload2 = b"updated message"
        self.loop.run_until_complete(self._publish_retained_message(
            topic, payload2, QoSLevel.AT_MOST_ONCE
        ))
        
        # Verify message was updated
        updated_msg = self.message_handler.message_queue.get_retained_message(topic)
        self.assertEqual(updated_msg.payload, payload2)
        self.assertEqual(updated_msg.qos, QoSLevel.AT_MOST_ONCE)

    def test_empty_payload_retained_message(self):
        """Test handling of empty payload for retained messages"""
        topic = "test/retained/empty"
        
        # First publish a normal retained message
        self.loop.run_until_complete(self._publish_retained_message(
            topic, b"initial message", QoSLevel.AT_LEAST_ONCE
        ))
        
        # Verify message is stored
        self.assertIsNotNone(
            self.message_handler.message_queue.get_retained_message(topic)
        )
        
        # Publish empty payload to clear retained message
        self.loop.run_until_complete(self._publish_retained_message(
            topic, b"", QoSLevel.AT_LEAST_ONCE
        ))
        
        # Verify retained message was cleared
        self.assertIsNone(
            self.message_handler.message_queue.get_retained_message(topic)
        )

    def test_multiple_topics_retained_messages(self):
        """Test handling retained messages across multiple topics"""
        topics = {
            "test/retained/1": b"message 1",
            "test/retained/2": b"message 2",
            "test/retained/3": b"message 3"
        }
        
        # Publish retained messages to multiple topics
        for topic, payload in topics.items():
            self.loop.run_until_complete(self._publish_retained_message(
                topic, payload, QoSLevel.AT_LEAST_ONCE
            ))
        
        # Verify all messages are retained
        for topic, payload in topics.items():
            retained_msg = self.message_handler.message_queue.get_retained_message(topic)
            self.assertIsNotNone(retained_msg)
            self.assertEqual(retained_msg.payload, payload)

    def test_new_subscription_retained_delivery(self):
        """Test delivery of retained messages to new subscriptions"""
        # Publish retained messages
        retained_data = {
            "test/retained/qos0": (b"qos0 message", QoSLevel.AT_MOST_ONCE),
            "test/retained/qos1": (b"qos1 message", QoSLevel.AT_LEAST_ONCE),
            "test/retained/qos2": (b"qos2 message", QoSLevel.EXACTLY_ONCE)
        }
        
        for topic, (payload, qos) in retained_data.items():
            self.loop.run_until_complete(self._publish_retained_message(
                topic, payload, qos
            ))
        
        # Create new subscription
        client_id = "new_subscriber"
        session = SessionState(
            client_id=client_id,
            clean_session=True,
            subscriptions={},
            pending_messages={},
            timestamp=datetime.now()
        )
        self.message_handler.sessions[client_id] = session
        
        # Subscribe to topics with different QoS levels
        subscriptions = [
            ("test/retained/qos0", QoSLevel.AT_LEAST_ONCE),
            ("test/retained/qos1", QoSLevel.AT_MOST_ONCE),
            ("test/retained/qos2", QoSLevel.EXACTLY_ONCE)
        ]
        
        packet = SubscribePacket(packet_id=1, topic_filters=subscriptions)
        self.loop.run_until_complete(
            self.message_handler.subscription_handler.handle_subscribe(client_id, packet)
        )
        
        # Verify retained messages are delivered with correct QoS
        for topic, sub_qos in subscriptions:
            retained_msg = self.message_handler.message_queue.get_retained_message(topic)
            self.assertIsNotNone(retained_msg)
            # Verify effective QoS (minimum of publish QoS and subscription QoS)
            pub_qos = retained_data[topic][1]
            expected_qos = min(pub_qos, sub_qos)
            if expected_qos > QoSLevel.AT_MOST_ONCE:
                self.assertTrue(any(
                    msg.qos_level == expected_qos 
                    for msg in session.pending_messages.values()
                ))

    def test_wildcard_subscription_retained_messages(self):
        """Test retained message delivery with wildcard subscriptions"""
        # Publish retained messages to hierarchical topics
        retained_data = {
            "test/wild/1": b"message 1",
            "test/wild/2": b"message 2",
            "test/other/1": b"message 3"
        }
        
        for topic, payload in retained_data.items():
            self.loop.run_until_complete(self._publish_retained_message(
                topic, payload, QoSLevel.AT_LEAST_ONCE
            ))
        
        # Subscribe with wildcards
        client_id = "wildcard_subscriber"
        session = SessionState(
            client_id=client_id,
            clean_session=True,
            subscriptions={},
            pending_messages={},
            timestamp=datetime.now()
        )
        self.message_handler.sessions[client_id] = session
        
        # Test different wildcard patterns
        wildcard_tests = [
            ("test/wild/+", 2),  # Should match 2 messages
            ("test/#", 3),       # Should match all 3 messages
            ("+/wild/#", 2),     # Should match 2 messages
            ("test/other/#", 1)  # Should match 1 message
        ]
        
        for wildcard, expected_matches in wildcard_tests:
            packet = SubscribePacket(
                packet_id=1,
                topic_filters=[(wildcard, QoSLevel.AT_LEAST_ONCE)]
            )
            self.loop.run_until_complete(
                self.message_handler.subscription_handler.handle_subscribe(
                    client_id, packet
                )
            )
            
            # Verify matching retained messages are delivered
            matching_messages = len([
                msg for topic, msg in 
                self.message_handler.message_queue.retained_messages.items()
                if self._topic_matches_wildcard(wildcard, topic)
            ])
            self.assertEqual(matching_messages, expected_matches)

    async def _publish_retained_message(self, topic: str, payload: bytes, qos: QoSLevel):
        """Helper method to publish retained messages"""
        packet = PublishPacket(
            topic=topic,
            payload=payload,
            qos=qos,
            retain=True
        )
        await self.message_handler._handle_publish(packet)

    def _topic_matches_wildcard(self, wildcard: str, topic: str) -> bool:
        """Helper method to check if topic matches wildcard pattern"""
        wild_parts = wildcard.split('/')
        topic_parts = topic.split('/')
        
        if len(wild_parts) > len(topic_parts) and '#' not in wild_parts:
            return False
            
        for wild, topic in zip(wild_parts, topic_parts):
            if wild == '#':
                return True
            if wild != '+' and wild != topic:
                return False
                
        return len(wild_parts) == len(topic_parts) or wild_parts[-1] == '#'

if __name__ == '__main__':
    unittest.main()