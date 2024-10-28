import unittest
import asyncio
from unittest.mock import Mock, patch
from datetime import datetime

from src.subscribe import (
    SubscribePacket,
    SubscriptionHandler,
    TopicNode,
    MessageType,
    QoSLevel
)

class TestTopicMatching(unittest.TestCase):
    """Test suite for topic matching functionality"""
    
    def setUp(self):
        self.subscription_handler = SubscriptionHandler()

    def test_exact_topic_match(self):
        """Test exact topic matching without wildcards"""
        self.subscription_handler._add_topic_node(
            ["home", "livingroom", "temp"],
            "client1",
            QoSLevel.AT_LEAST_ONCE
        )
        
        matches = self.subscription_handler.get_matching_subscribers("home/livingroom/temp")
        self.assertEqual(len(matches), 1)
        self.assertIn("client1", matches)
        self.assertEqual(matches["client1"], QoSLevel.AT_LEAST_ONCE)

    def test_single_level_wildcard_match(self):
        """Test topic matching with single-level (+) wildcard"""
        self.subscription_handler._add_topic_node(
            ["home", "+", "temp"],
            "client1",
            QoSLevel.AT_MOST_ONCE
        )
        
        matches = self.subscription_handler.get_matching_subscribers("home/livingroom/temp")
        self.assertEqual(len(matches), 1)
        self.assertIn("client1", matches)
        
        matches = self.subscription_handler.get_matching_subscribers("home/kitchen/temp")
        self.assertEqual(len(matches), 1)
        self.assertIn("client1", matches)

    def test_multi_level_wildcard_match(self):
        """Test topic matching with multi-level (#) wildcard"""
        self.subscription_handler._add_topic_node(
            ["home", "#"],
            "client1",
            QoSLevel.EXACTLY_ONCE
        )
        
        matches = self.subscription_handler.get_matching_subscribers("home/livingroom/temp")
        self.assertEqual(len(matches), 1)
        self.assertIn("client1", matches)
        
        matches = self.subscription_handler.get_matching_subscribers("home/kitchen/humidity")
        self.assertEqual(len(matches), 1)
        self.assertIn("client1", matches)

    def test_nested_topic_structure(self):
        """Test matching with nested topic structure"""
        self.subscription_handler._add_topic_node(
            ["home", "livingroom", "+", "sensor1"],
            "client1",
            QoSLevel.AT_LEAST_ONCE
        )
        self.subscription_handler._add_topic_node(
            ["home", "livingroom", "#"],
            "client2",
            QoSLevel.AT_MOST_ONCE
        )
        
        matches = self.subscription_handler.get_matching_subscribers("home/livingroom/temp/sensor1")
        self.assertEqual(len(matches), 2)
        self.assertIn("client1", matches)
        self.assertIn("client2", matches)

class TestSubscriptionManagement(unittest.TestCase):
    """Test suite for subscription management"""
    
    def setUp(self):
        self.subscription_handler = SubscriptionHandler()

    def test_add_subscription(self):
        """Test adding a new subscription"""
        client_id = "client1"
        topic = "test/topic"
        qos = QoSLevel.AT_LEAST_ONCE
        
        self.subscription_handler._add_topic_node(
            topic.split('/'),
            client_id,
            qos
        )
        
        matches = self.subscription_handler.get_matching_subscribers(topic)
        self.assertIn(client_id, matches)
        self.assertEqual(matches[client_id], qos)

    def test_multiple_subscriptions_per_client(self):
        """Test handling multiple subscriptions for a single client"""
        client_id = "client1"
        subscriptions = [
            ("test/topic1", QoSLevel.AT_MOST_ONCE),
            ("test/topic2", QoSLevel.AT_LEAST_ONCE),
            ("test/topic3", QoSLevel.EXACTLY_ONCE)
        ]
        
        for topic, qos in subscriptions:
            self.subscription_handler._add_topic_node(
                topic.split('/'),
                client_id,
                qos
            )
        
        for topic, expected_qos in subscriptions:
            matches = self.subscription_handler.get_matching_subscribers(topic)
            self.assertIn(client_id, matches)
            self.assertEqual(matches[client_id], expected_qos)

    def test_subscription_qos_levels(self):
        """Test handling different QoS levels for subscriptions"""
        self.subscription_handler._add_topic_node(
            ["test", "topic"],
            "client1",
            QoSLevel.AT_LEAST_ONCE
        )
        self.subscription_handler._add_topic_node(
            ["test", "topic"],
            "client2",
            QoSLevel.EXACTLY_ONCE
        )
        
        matches = self.subscription_handler.get_matching_subscribers("test/topic")
        self.assertEqual(matches["client1"], QoSLevel.AT_LEAST_ONCE)
        self.assertEqual(matches["client2"], QoSLevel.EXACTLY_ONCE)

class TestSubscribePacketHandling(unittest.IsolatedAsyncioTestCase):
    """Test suite for SUBSCRIBE packet handling"""
    
    async def asyncSetUp(self):
        self.subscription_handler = SubscriptionHandler()

    def test_subscribe_packet_encoding(self):
        """Test SUBSCRIBE packet encoding"""
        packet = SubscribePacket(
            packet_id=1,
            topic_filters=[("test/topic", QoSLevel.AT_LEAST_ONCE)]
        )
        
        encoded = packet.encode()
        self.assertIsInstance(encoded, bytes)
        
        # Verify packet structure
        self.assertEqual(encoded[0] >> 4, MessageType.SUBSCRIBE)
        self.assertEqual(encoded[0] & 0x02, 0x02)  # QoS 1 required
        self.assertEqual(int.from_bytes(encoded[2:4], 'big'), 1)  # Packet ID

    async def test_handle_subscribe_packet(self):
        """Test handling of SUBSCRIBE packet"""
        packet = SubscribePacket(
            packet_id=1,
            topic_filters=[
                ("test/topic1", QoSLevel.AT_MOST_ONCE),
                ("test/topic2", QoSLevel.AT_LEAST_ONCE)
            ]
        )
        
        return_codes = await self.subscription_handler.handle_subscribe(
            "client1",
            packet
        )
        
        self.assertEqual(len(return_codes), 2)
        self.assertEqual(return_codes[0], QoSLevel.AT_MOST_ONCE)
        self.assertEqual(return_codes[1], QoSLevel.AT_LEAST_ONCE)

    async def test_handle_invalid_topic_filter(self):
        """Test handling of invalid topic filters"""
        packet = SubscribePacket(
            packet_id=1,
            topic_filters=[
                ("test/#/invalid", QoSLevel.AT_MOST_ONCE),  # Invalid multi-level wildcard
                ("", QoSLevel.AT_LEAST_ONCE)  # Empty topic
            ]
        )
        
        return_codes = await self.subscription_handler.handle_subscribe(
            "client1",
            packet
        )
        
        self.assertEqual(len(return_codes), 2)
        self.assertEqual(return_codes[0], 0x80)  # Failure
        self.assertEqual(return_codes[1], 0x80)  # Failure

    async def test_suback_generation(self):
        """Test SUBACK packet generation"""
        mock_writer = Mock(spec=asyncio.StreamWriter)
        return_codes = [QoSLevel.AT_MOST_ONCE, QoSLevel.AT_LEAST_ONCE]
        
        await self.subscription_handler.send_suback(mock_writer, 1, return_codes)
        
        mock_writer.write.assert_called_once()
        mock_writer.drain.assert_called_once()
        written_data = mock_writer.write.call_args[0][0]
        
        # Verify SUBACK packet structure
        self.assertEqual(written_data[0] >> 4, MessageType.SUBACK)
        self.assertEqual(int.from_bytes(written_data[2:4], 'big'), 1)  # Packet ID
        self.assertEqual(list(written_data[4:]), return_codes)  # Return codes

if __name__ == '__main__':
    unittest.main()