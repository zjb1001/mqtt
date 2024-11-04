import unittest
from datetime import datetime
import asyncio

# Add src into path
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.message_handler import (
    MessageHandler, MessageQueue, Message, 
    RetainedMessage, QoSMessage
)
from src.will_message import QoSLevel
from src.publish import PublishHandler, PublishPacket
from src.subscribe import SubscriptionHandler, SubscribePacket
from src.session import SessionState

class TestMessageFlow(unittest.TestCase):
    """Test suite for MQTT message flow using real handlers"""

    def setUp(self):
        """Set up test fixtures with real handlers"""
        self.message_handler = MessageHandler()
        self.publish_handler = PublishHandler()
        self.subscription_handler = SubscriptionHandler()

    async def _setup_session(self, client_id: str, clean_session: bool = True) -> SessionState:
        """Helper method to create and setup a client session"""
        session = SessionState(
            client_id=client_id,
            clean_session=clean_session,
            subscriptions={},
            pending_messages={},
            timestamp=datetime.now()
        )
        self.message_handler.sessions[client_id] = session
        return session

    async def _subscribe_client(self, client_id: str, topic: str, qos: QoSLevel) -> None:
        """Helper method to subscribe a client to a topic"""
        packet = SubscribePacket(
            packet_id=self.publish_handler._get_next_packet_id(),
            topic_filters=[(topic, qos)]
        )
        return_codes = await self.subscription_handler.handle_subscribe(client_id, packet)
        self.assertEqual(return_codes[0], qos)

    async def test_single_publisher_multiple_subscribers(self):
        """Test scenario with one publisher and multiple subscribers at different QoS levels"""
        # Setup subscribers
        sub_configs = [
            ("sub1", QoSLevel.AT_MOST_ONCE),
            ("sub2", QoSLevel.AT_LEAST_ONCE),
            ("sub3", QoSLevel.EXACTLY_ONCE)
        ]
        
        # Create sessions and subscribe clients
        for client_id, qos in sub_configs:
            await self._setup_session(client_id)
            await self._subscribe_client(client_id, "test/topic", qos)
        
        # Publish message at QoS 2
        publish_packet = PublishPacket(
            topic="test/topic",
            payload=b"multi-subscriber test",
            qos=QoSLevel.EXACTLY_ONCE,
            retain=False,
            packet_id=1
        )
        
        # Process publish packet
        await self.message_handler._handle_publish(publish_packet)
        
        # Verify message delivery based on subscriber QoS
        # QoS 0 subscriber should have no pending messages
        self.assertEqual(len(self.message_handler.sessions["sub1"].pending_messages), 0)
        
        # QoS 1 subscriber should have pending message
        sub2_messages = self.message_handler.sessions["sub2"].pending_messages
        self.assertEqual(len(sub2_messages), 1)
        
        # QoS 2 subscriber should have pending message
        sub3_messages = self.message_handler.sessions["sub3"].pending_messages
        self.assertEqual(len(sub3_messages), 1)
        
        # Complete QoS 1 flow for sub2
        first_msg_id = list(sub2_messages.keys())[0]
        await self.message_handler.handle_message_acknowledgment(
            "sub2", first_msg_id, "PUBACK"
        )
        self.assertEqual(len(self.message_handler.sessions["sub2"].pending_messages), 0)
        
        # Complete QoS 2 flow for sub3
        second_msg_id = list(sub3_messages.keys())[0]
        await self.message_handler.handle_message_acknowledgment(
            "sub3", second_msg_id, "PUBREC"
        )
        await self.message_handler.handle_message_acknowledgment(
            "sub3", second_msg_id, "PUBREL"
        )
        await self.message_handler.handle_message_acknowledgment(
            "sub3", second_msg_id, "PUBCOMP"
        )
        self.assertEqual(len(self.message_handler.sessions["sub3"].pending_messages), 0)

    async def test_multiple_publishers_single_subscriber(self):
        """Test scenario with multiple publishers sending to a single subscriber"""
        # Setup subscriber
        subscriber_id = "subscriber1"
        await self._setup_session(subscriber_id)
        await self._subscribe_client(subscriber_id, "test/topic/#", QoSLevel.EXACTLY_ONCE)
        
        # Setup publisher sessions
        publisher_ids = ["pub1", "pub2", "pub3"]
        for pub_id in publisher_ids:
            await self._setup_session(pub_id)
        
        # Publishers send messages with different QoS levels
        publish_configs = [
            ("pub1", QoSLevel.AT_MOST_ONCE, "test/topic/1"),
            ("pub2", QoSLevel.AT_LEAST_ONCE, "test/topic/2"),
            ("pub3", QoSLevel.EXACTLY_ONCE, "test/topic/3")
        ]
        
        msg_id = 1
        for pub_id, qos, topic in publish_configs:
            packet = PublishPacket(
                topic=topic,
                payload=f"Message from {pub_id}".encode(),
                qos=qos,
                retain=False,
                packet_id=msg_id
            )
            await self.message_handler._handle_publish(packet)
            msg_id += 1
        
        # Verify message reception
        subscriber_messages = self.message_handler.sessions[subscriber_id].pending_messages
        # Should have 2 pending messages (QoS 1 and QoS 2)
        self.assertEqual(len(subscriber_messages), 2)

    async def test_session_persistence_and_message_delivery(self):
        """Test session persistence and message delivery with clean/persistent sessions"""
        # Setup persistent session
        persistent_client = "persistent_client"
        await self._setup_session(persistent_client, clean_session=False)
        await self._subscribe_client(persistent_client, "test/persist", QoSLevel.AT_LEAST_ONCE)
        
        # Publish messages while client is "offline"
        for i in range(3):
            packet = PublishPacket(
                topic="test/persist",
                payload=f"Offline message {i}".encode(),
                qos=QoSLevel.AT_LEAST_ONCE,
                retain=False,
                packet_id=i+1
            )
            await self.message_handler._handle_publish(packet)
        
        # Verify messages are stored in session
        session = self.message_handler.sessions[persistent_client]
        self.assertEqual(len(session.pending_messages), 3)
        
        # Simulate client reconnection and message acknowledgment
        for msg_id in range(1, 4):
            await self.message_handler.handle_message_acknowledgment(
                persistent_client, msg_id, "PUBACK"
            )
        
        # Verify messages are cleared after acknowledgment
        self.assertEqual(len(session.pending_messages), 0)

    async def test_mixed_qos_levels(self):
        """Test handling of mixed QoS levels between publishers and subscribers"""
        # Setup subscriber with mixed QoS subscriptions
        subscriber_id = "mixed_sub"

    async def test_retained_messages_with_session_persistence(self):
        """Test retained message interaction with session persistence in real environment"""
        # Setup publisher and send retained message
        publisher_id = "retained_pub"
        await self._setup_session(publisher_id)
        
        # Send multiple retained messages on different topics
        retained_messages = [
            ("test/retained1", b"retained message 1", QoSLevel.AT_LEAST_ONCE),
            ("test/retained2", b"retained message 2", QoSLevel.EXACTLY_ONCE)
        ]
        
        for topic, payload, qos in retained_messages:
            packet = PublishPacket(
                topic=topic,
                payload=payload,
                qos=qos,
                retain=True,
                packet_id=self.publish_handler._get_next_packet_id()
            )
            await self.message_handler._handle_publish(packet)
        
        # Create persistent session with multiple subscriptions
        subscriber_id = "retained_sub"
        await self._setup_session(subscriber_id, clean_session=False)
        
        # Subscribe to topics in multiple batches
        await self._subscribe_client(subscriber_id, "test/retained1", QoSLevel.AT_LEAST_ONCE)
        # Simulate network delay
        await asyncio.sleep(0.1)
        await self._subscribe_client(subscriber_id, "test/retained2", QoSLevel.EXACTLY_ONCE)
        
        # Verify all retained messages are delivered with correct QoS
        subscriber_messages = self.message_handler.sessions[subscriber_id].pending_messages
        self.assertEqual(len(subscriber_messages), 2)
        
        # Verify message properties and complete flows
        for msg_id, msg in subscriber_messages.items():
            if msg.topic == "test/retained1":
                # Complete QoS 1 flow
                await self.message_handler.handle_message_acknowledgment(
                    subscriber_id, msg_id, "PUBACK"
                )
            else:
                # Complete QoS 2 flow
                await self.message_handler.handle_message_acknowledgment(
                    subscriber_id, msg_id, "PUBREC"
                )
                await self.message_handler.handle_message_acknowledgment(
                    subscriber_id, msg_id, "PUBREL"
                )
                await self.message_handler.handle_message_acknowledgment(
                    subscriber_id, msg_id, "PUBCOMP"
                )
        
        # Verify all messages are cleared
        self.assertEqual(len(self.message_handler.sessions[subscriber_id].pending_messages), 0)

    async def test_high_throughput_message_ordering(self):
        """Test message ordering under high load with multiple publishers and subscribers"""
        NUM_MESSAGES = 100
        NUM_PUBLISHERS = 3
        NUM_SUBSCRIBERS = 2
        
        # Setup subscribers
        subscriber_ids = [f"order_sub_{i}" for i in range(NUM_SUBSCRIBERS)]
        for sub_id in subscriber_ids:
            await self._setup_session(sub_id)
            await self._subscribe_client(sub_id, "test/order/#", QoSLevel.EXACTLY_ONCE)
        
        # Setup publishers
        publisher_ids = [f"order_pub_{i}" for i in range(NUM_PUBLISHERS)]
        for pub_id in publisher_ids:
            await self._setup_session(pub_id)
        
        # Send messages from all publishers
        publish_tasks = []
        expected_messages = {}
        
        for pub_id in publisher_ids:
            messages = []
            for i in range(NUM_MESSAGES):
                topic = f"test/order/{pub_id}"
                payload = f"{pub_id}_message_{i}".encode()
                packet = PublishPacket(
                    topic=topic,
                    payload=payload,
                    qos=QoSLevel.EXACTLY_ONCE,
                    retain=False,
                    packet_id=self.publish_handler._get_next_packet_id()
                )
                messages.append((topic, payload))
                publish_tasks.append(self.message_handler._handle_publish(packet))
            expected_messages[pub_id] = messages
        
        # Wait for all publishes to complete
        await asyncio.gather(*publish_tasks)
        
        # Verify message ordering for each subscriber
        for sub_id in subscriber_ids:
            subscriber_messages = self.message_handler.sessions[sub_id].pending_messages
            
            # Group messages by publisher
            received_messages = {}
            for msg_id, msg in subscriber_messages.items():
                pub_id = msg.topic.split('/')[-1]
                if pub_id not in received_messages:
                    received_messages[pub_id] = []
                received_messages[pub_id].append((msg.topic, msg.payload))
            
            # Verify order for each publisher
            for pub_id, messages in expected_messages.items():
                received = received_messages.get(pub_id, [])
                self.assertEqual(len(received), len(messages))
                for i, (exp_topic, exp_payload) in enumerate(messages):
                    self.assertEqual(received[i][0], exp_topic)
                    self.assertEqual(received[i][1], exp_payload)
        await self._setup_session(subscriber_id)
        
        # Subscribe to multiple topics with different QoS
        subscriptions = [
            ("test/qos0", QoSLevel.AT_MOST_ONCE),
            ("test/qos1", QoSLevel.AT_LEAST_ONCE),
            ("test/qos2", QoSLevel.EXACTLY_ONCE)
        ]
        
        for topic, qos in subscriptions:
            await self._subscribe_client(subscriber_id, topic, qos)
        
        # Publish messages with different QoS to each topic
        messages = [
            # Higher QoS publish to lower QoS subscription
            ("test/qos0", QoSLevel.EXACTLY_ONCE, 1),
            # Matching QoS levels
            ("test/qos1", QoSLevel.AT_LEAST_ONCE, 2),
            # Lower QoS publish to higher QoS subscription
            ("test/qos2", QoSLevel.AT_MOST_ONCE, 3)
        ]
        
        for topic, pub_qos, msg_id in messages:
            packet = PublishPacket(
                topic=topic,
                payload=f"QoS test message".encode(),
                qos=pub_qos,
                retain=False,
                packet_id=msg_id
            )
            await self.message_handler._handle_publish(packet)
        
        # Verify message handling
        session = self.message_handler.sessions[subscriber_id]
        pending_messages = session.pending_messages
        
        # Should have 1 pending message (QoS 1 message to QoS 1 subscription)
        # QoS 0 subscription receives no pending messages
        # QoS 0 publish to QoS 2 subscription creates no pending message
        self.assertEqual(len(pending_messages), 1)
        
        # Complete the QoS 1 flow
        await self.message_handler.handle_message_acknowledgment(
            subscriber_id, 2, "PUBACK"
        )
        self.assertEqual(len(pending_messages), 0)

if __name__ == '__main__':
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add test cases to suite
    test_cases = [
        TestMessageFlow("test_single_publisher_multiple_subscribers"),
        TestMessageFlow("test_multiple_publishers_single_subscriber"),
        TestMessageFlow("test_session_persistence_and_message_delivery"),
        TestMessageFlow("test_mixed_qos_levels"),
        TestMessageFlow("test_retained_messages_with_session_persistence"),
        TestMessageFlow("test_high_throughput_message_ordering")
    ]
    
    # Add test cases to suite
    for test in test_cases:
        suite.addTest(test)
    
    # Run test suite
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)