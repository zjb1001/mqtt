import unittest
import asyncio
from unittest.mock import Mock, patch
from datetime import datetime

# add src into path, src path upper level two from this file
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.subscribe import (
    SubscribePacket,
    SubscriptionHandler,
    TopicNode,
    MessageType,
    QoSLevel,
    SessionState
)

class TestInternalTopicMatching(unittest.TestCase):
    """Test suite for internal topic matching functionality"""
    
    def setUp(self):
        self.subscription_handler = SubscriptionHandler()

    def test_internal_add_topic_node(self):
        """Test internal topic node addition"""
        self.subscription_handler._add_topic_node(
            ["home", "livingroom", "temp"],
            "client1",
            QoSLevel.AT_LEAST_ONCE
        )
        
        # Verify internal node structure
        root = self.subscription_handler.topic_tree
        self.assertIn("home", root.children)
        self.assertIn("livingroom", root.children["home"].children)
        self.assertIn("temp", root.children["home"].children["livingroom"].children)
        
        node = root.children["home"].children["livingroom"].children["temp"]
        # Verify that client1 is in the subscribers set
        self.assertIn("client1", node.subscribers)

class TestPublicTopicMatching(unittest.TestCase):
    """Test suite for public topic matching API"""
    
    def setUp(self):
        self.subscription_handler = SubscriptionHandler()

        # Create mock sessions with subscriptions
        self.client1_subscriptions = {
            "home/livingroom/temp": QoSLevel.AT_LEAST_ONCE,
            "home/+/temp": QoSLevel.AT_MOST_ONCE,
            "home/#": QoSLevel.EXACTLY_ONCE,
            "home/livingroom/+/sensor1": QoSLevel.AT_LEAST_ONCE
        }
        
        self.client2_subscriptions = {
            "home/livingroom/#": QoSLevel.AT_MOST_ONCE
        }

        # Create mock sessions
        self.subscription_handler.sessions = {
            "client1": Mock(subscriptions=self.client1_subscriptions),
            "client2": Mock(subscriptions=self.client2_subscriptions)
        }

        # Add subscriptions to the topic tree
        for topic, qos in self.client1_subscriptions.items():
            topic_parts = topic.split("/")
            if "#" in topic_parts:
                # For multi-level wildcards, only include parts up to #
                idx = topic_parts.index("#")
                topic_parts = topic_parts[:idx+1]
            self.subscription_handler._add_topic_node(topic_parts, "client1", qos)
        
        for topic, qos in self.client2_subscriptions.items():
            topic_parts = topic.split("/")
            if "#" in topic_parts:
                idx = topic_parts.index("#")
                topic_parts = topic_parts[:idx+1]
            self.subscription_handler._add_topic_node(topic_parts, "client2", qos)

    async def test_exact_topic_match(self):
        # Test exact topic matching
        matches = self.subscription_handler.get_matching_subscribers("home/livingroom/temp")
        self.assertIn("client1", matches)
        self.assertEqual(matches["client1"], QoSLevel.AT_LEAST_ONCE)
        
        # Verify non-matching topic returns empty result
        non_matches = self.subscription_handler.get_matching_subscribers("home/kitchen/temp")
        self.assertIn("client1", non_matches)

    async def test_single_level_wildcard_match(self):
        """Test topic matching with single-level (+) wildcard"""
        packet = SubscribePacket(
            packet_id=1,
            topic_filters=[("home/+/temp", QoSLevel.AT_MOST_ONCE)]
        )
        return_codes = await self.subscription_handler.handle_subscribe("client1", packet)
        self.assertEqual(return_codes[0], QoSLevel.AT_MOST_ONCE)

        matches = self.subscription_handler.get_matching_subscribers("home/livingroom/temp")
        self.assertIn("client1", matches)
        
        matches = self.subscription_handler.get_matching_subscribers("home/kitchen/temp") 
        self.assertIn("client1", matches)

    def test_multi_level_wildcard_match(self):
        """Test topic matching with multi-level (#) wildcard"""
        matches = self.subscription_handler.get_matching_subscribers("home/livingroom/temp")
        self.assertIn("client1", matches)
        
        matches = self.subscription_handler.get_matching_subscribers("home/kitchen/humidity")
        self.assertIn("client1", matches)

    def test_nested_topic_structure(self):
        """Test matching with nested topic structure"""
        matches = self.subscription_handler.get_matching_subscribers("home/livingroom/temp/sensor1")
        self.assertEqual(len(matches), 2)
        self.assertIn("client1", matches)
        self.assertIn("client2", matches)

class TestPublicSubscriptionManagement(unittest.IsolatedAsyncioTestCase):
    """Test suite for public subscription management API with real packet handling"""
    
    async def asyncSetUp(self):
        """Set up test environment before each test"""
        self.subscription_handler = SubscriptionHandler()
        self.client_id = "test_client"
        
        # Create a real session for testing
        self.session = SessionState(
            client_id=self.client_id,
            clean_session=True,
            subscriptions={},
            pending_messages={},
            timestamp=datetime.now()
        )
        self.subscription_handler.sessions[self.client_id] = self.session

    async def test_basic_subscription_handling(self):
        """Test basic subscription handling with real packet"""
        # Setup
        topic = "sensors/temperature"
        qos = QoSLevel.AT_LEAST_ONCE
        
        # Create and process subscription packet
        packet = SubscribePacket(
            packet_id=1,
            topic_filters=[(topic, qos)]
        )
        return_codes = await self.subscription_handler.handle_subscribe(self.client_id, packet)
        
        # Verify subscription was processed correctly
        self.assertEqual(len(return_codes), 1)
        self.assertEqual(return_codes[0], qos)
        self.assertEqual(self.session.subscriptions[topic], qos)
        
        # Test that subscriber receives matching messages
        matches = self.subscription_handler.get_matching_subscribers(topic)
        self.assertIn(self.client_id, matches)
        self.assertEqual(matches[self.client_id], qos)

    async def test_multiple_topic_subscription(self):
        """Test subscribing to multiple topics with real packet"""
        # Setup - mix of simple topics and wildcards
        subscriptions = [
            ("home/livingroom/temperature", QoSLevel.AT_MOST_ONCE),
            ("home/+/humidity", QoSLevel.AT_LEAST_ONCE),
            ("sensors/#", QoSLevel.EXACTLY_ONCE)
        ]
        
        # Create and process subscription packet
        packet = SubscribePacket(packet_id=1, topic_filters=subscriptions)
        return_codes = await self.subscription_handler.handle_subscribe(self.client_id, packet)
        
        # Verify all subscriptions were processed
        self.assertEqual(len(return_codes), len(subscriptions))
        for (topic, qos), code in zip(subscriptions, return_codes):
            self.assertEqual(code, qos)
            self.assertEqual(self.session.subscriptions[topic], qos)
        
        # Test matching with different topic patterns
        test_topics = [
            "home/livingroom/temperature",  # Exact match
            "home/kitchen/humidity",        # Single-level wildcard match
            "sensors/temp/1",               # Multi-level wildcard match
            "sensors/humidity/basement/2"    # Multi-level wildcard match
        ]
        
        for topic in test_topics:
            matches = self.subscription_handler.get_matching_subscribers(topic)
            self.assertIn(self.client_id, matches)

    async def test_duplicate_subscription_handling(self):
        """Test handling of duplicate subscriptions with different QoS levels"""
        # Setup
        topic = "test/duplicate"
        
        # First subscription
        packet1 = SubscribePacket(
            packet_id=1,
            topic_filters=[(topic, QoSLevel.AT_MOST_ONCE)]
        )
        await self.subscription_handler.handle_subscribe(self.client_id, packet1)
        
        # Verify first subscription
        self.assertEqual(self.session.subscriptions[topic], QoSLevel.AT_MOST_ONCE)
        
        # Second subscription with higher QoS
        packet2 = SubscribePacket(
            packet_id=2,
            topic_filters=[(topic, QoSLevel.EXACTLY_ONCE)]
        )
        return_codes = await self.subscription_handler.handle_subscribe(self.client_id, packet2)
        
        # Verify QoS was upgraded
        self.assertEqual(return_codes[0], QoSLevel.EXACTLY_ONCE)
        self.assertEqual(self.session.subscriptions[topic], QoSLevel.EXACTLY_ONCE)
        matches = self.subscription_handler.get_matching_subscribers(topic)
        self.assertEqual(matches[self.client_id], QoSLevel.EXACTLY_ONCE)

    async def test_invalid_subscription_handling(self):
        """Test handling of invalid subscription requests"""
        invalid_subscriptions = [
            ("", QoSLevel.AT_MOST_ONCE),                # Empty topic
            ("test/#/invalid", QoSLevel.AT_LEAST_ONCE), # Invalid wildcard position
            ("test//topic", QoSLevel.EXACTLY_ONCE),     # Empty level
            ("#/test", QoSLevel.AT_MOST_ONCE),         # Invalid wildcard usage
            ("test/+#", QoSLevel.AT_LEAST_ONCE)        # Invalid wildcard combination
        ]
        
        packet = SubscribePacket(packet_id=1, topic_filters=invalid_subscriptions)
        return_codes = await self.subscription_handler.handle_subscribe(self.client_id, packet)
        
        # Verify all invalid subscriptions were rejected
        self.assertEqual(len(return_codes), len(invalid_subscriptions))
        for code in return_codes:
            self.assertEqual(code, 0x80)  # Failure code
        
        # Verify no invalid subscriptions were added
        self.assertEqual(len(self.session.subscriptions), 0)

    async def test_subscription_cleanup(self):
        """Test subscription cleanup on session termination"""
        # Setup - add some subscriptions
        subscriptions = [
            ("test/topic1", QoSLevel.AT_MOST_ONCE),
            ("test/topic2", QoSLevel.AT_LEAST_ONCE)
        ]
        
        packet = SubscribePacket(packet_id=1, topic_filters=subscriptions)
        await self.subscription_handler.handle_subscribe(self.client_id, packet)
        
        # Verify subscriptions were added
        for topic, qos in subscriptions:
            self.assertIn(topic, self.session.subscriptions)
        
        # Simulate session cleanup
        del self.subscription_handler.sessions[self.client_id]
        
        # Verify subscriptions were removed
        for topic, _ in subscriptions:
            matches = self.subscription_handler.get_matching_subscribers(topic)
            self.assertNotIn(self.client_id, matches)

    async def test_wildcard_subscription_matching(self):
        """Test wildcard subscription matching patterns"""
        # Setup wildcard subscriptions
        wildcard_subscriptions = [
            ("home/+/temperature", QoSLevel.AT_MOST_ONCE),
            ("sensors/#", QoSLevel.AT_LEAST_ONCE)
        ]
        
        packet = SubscribePacket(packet_id=1, topic_filters=wildcard_subscriptions)
        await self.subscription_handler.handle_subscribe(self.client_id, packet)
        
        # Test single-level wildcard matching
        single_level_matches = [
            "home/kitchen/temperature",
            "home/livingroom/temperature",
            "home/bedroom/temperature"
        ]
        
        for topic in single_level_matches:
            matches = self.subscription_handler.get_matching_subscribers(topic)
            self.assertIn(self.client_id, matches)
            self.assertEqual(matches[self.client_id], QoSLevel.AT_MOST_ONCE)
        
        # Test multi-level wildcard matching
        multi_level_matches = [
            "sensors/temp",
            "sensors/temp/1",
            "sensors/humidity/basement"
        ]
        
        for topic in multi_level_matches:
            matches = self.subscription_handler.get_matching_subscribers(topic)
            self.assertIn(self.client_id, matches)
            self.assertEqual(matches[self.client_id], QoSLevel.AT_LEAST_ONCE)

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
        
        # Create mock session
        self.subscription_handler.sessions["client1"] = Mock(
            subscriptions={},
            clean_session=True
        )
        
        return_codes = await self.subscription_handler.handle_subscribe(
            "client1",
            packet
        )
        
        self.assertEqual(len(return_codes), 2)
        self.assertEqual(return_codes[0], QoSLevel.AT_MOST_ONCE)
        self.assertEqual(return_codes[1], QoSLevel.AT_LEAST_ONCE)
        
        # Verify topic tree structure
        root = self.subscription_handler.topic_tree
        self.assertIn("test", root.children)
        self.assertIn("topic1", root.children["test"].children)
        self.assertIn("topic2", root.children["test"].children)

    async def test_topic_segment_handling(self):
        """Test handling of topic segments"""
        packet = SubscribePacket(
            packet_id=1,
            topic_filters=[("a/b/c", QoSLevel.AT_MOST_ONCE)]
        )
        
        # Create mock session
        self.subscription_handler.sessions["client1"] = Mock(
            subscriptions={},
            clean_session=True
        )
        
        return_codes = await self.subscription_handler.handle_subscribe(
            "client1",
            packet
        )
        
        # Verify each segment was added correctly
        root = self.subscription_handler.topic_tree
        self.assertIn("a", root.children)
        self.assertIn("b", root.children["a"].children)
        self.assertIn("c", root.children["a"].children["b"].children)
        
        # Verify subscriber was added
        leaf_node = root.children["a"].children["b"].children["c"]
        self.assertIn("client1", leaf_node.subscribers)
        self.assertEqual(leaf_node.subscribers["client1"], QoSLevel.AT_MOST_ONCE)

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

if __name__ == "__main__":
    """Run subscription test suites"""
    suite = unittest.TestSuite()
    
    # # Add test classes to suite
    suite.addTest(TestInternalTopicMatching("test_internal_add_topic_node"))

    suite.addTest(TestPublicTopicMatching("test_exact_topic_match"))
    suite.addTest(TestPublicTopicMatching("test_single_level_wildcard_match"))
    suite.addTest(TestPublicTopicMatching("test_multi_level_wildcard_match"))
    suite.addTest(TestPublicTopicMatching("test_nested_topic_structure"))

    suite.addTest(TestPublicSubscriptionManagement("test_basic_subscription_handling"))
    suite.addTest(TestPublicSubscriptionManagement("test_multiple_topic_subscription"))
    suite.addTest(TestPublicSubscriptionManagement("test_duplicate_subscription_handling"))
    suite.addTest(TestPublicSubscriptionManagement("test_invalid_subscription_handling"))
    suite.addTest(TestPublicSubscriptionManagement("test_subscription_cleanup"))
    suite.addTest(TestPublicSubscriptionManagement("test_wildcard_subscription_matching"))

    suite.addTest(TestSubscribePacketHandling("test_subscribe_packet_encoding"))
    suite.addTest(TestSubscribePacketHandling("test_handle_subscribe_packet"))
    suite.addTest(TestSubscribePacketHandling("test_suback_generation"))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite).wasSuccessful()

