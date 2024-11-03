import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

# add src into path, src path upper level two from this file
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.will_message import WillMessage, QoSLevel

class TestWillMessageSetup(unittest.TestCase):
    """Test suite for MQTT will message setup and properties"""
    
    def setUp(self):
        """Set up test fixtures before each test method"""
        self.topic = "test/will"
        self.payload = b"client disconnected"
        self.qos = QoSLevel.AT_LEAST_ONCE
        self.retain = True
        self.delay_interval = 30
        
        self.will_message = WillMessage(
            topic=self.topic,
            payload=self.payload,
            qos=self.qos,
            retain=self.retain,
            delay_interval=self.delay_interval
        )

    def test_will_message_creation(self):
        """Test creating a new will message with all properties"""
        self.assertEqual(self.will_message.topic, self.topic)
        self.assertEqual(self.will_message.payload, self.payload)
        self.assertEqual(self.will_message.qos, QoSLevel.AT_LEAST_ONCE)
        self.assertTrue(self.will_message.retain)
        self.assertEqual(self.will_message.delay_interval, self.delay_interval)

    def test_will_message_default_values(self):
        """Test will message creation with default values"""
        basic_will = WillMessage(
            topic="test/basic",
            payload=b"basic message",
            qos=QoSLevel.AT_MOST_ONCE,
            retain=False
        )
        
        self.assertEqual(basic_will.delay_interval, 0)
        self.assertFalse(basic_will.retain)
        self.assertEqual(basic_will.qos, QoSLevel.AT_MOST_ONCE)

    def test_will_message_payload_types(self):
        """Test will message with different payload types"""
        # Test with empty payload
        empty_will = WillMessage(
            topic="test/empty",
            payload=b"",
            qos=QoSLevel.AT_MOST_ONCE,
            retain=False
        )
        self.assertEqual(empty_will.payload, b"")
        
        # Test with UTF-8 encoded payload
        utf8_payload = "测试消息".encode('utf-8')
        utf8_will = WillMessage(
            topic="test/utf8",
            payload=utf8_payload,
            qos=QoSLevel.AT_MOST_ONCE,
            retain=False
        )
        self.assertEqual(utf8_will.payload, utf8_payload)

    def test_qos_level_validation(self):
        """Test QoS level enumeration values"""
        self.assertEqual(QoSLevel.AT_MOST_ONCE.value, 0)
        self.assertEqual(QoSLevel.AT_LEAST_ONCE.value, 1)
        self.assertEqual(QoSLevel.EXACTLY_ONCE.value, 2)
        
        # Test all valid QoS levels
        for qos in QoSLevel:
            will = WillMessage(
                topic="test/qos",
                payload=b"test",
                qos=qos,
                retain=False
            )
            self.assertIsInstance(will.qos, QoSLevel)

class TestWillMessageBehavior(unittest.TestCase):
    """Test suite for will message behavior and triggers"""

    def setUp(self):
        self.will_message = WillMessage(
            topic="test/will",
            payload=b"disconnected",
            qos=QoSLevel.EXACTLY_ONCE,
            retain=True,
            delay_interval=60
        )

    # def test_will_message_immutability(self):
    #     """Test that will message properties cannot be modified after creation"""
    #     with self.assertRaises(AttributeError):
    #         self.will_message.topic = "new/topic"
        
    #     with self.assertRaises(AttributeError):
    #         self.will_message.payload = b"new payload"
            
    #     with self.assertRaises(AttributeError):
    #         self.will_message.qos = QoSLevel.AT_MOST_ONCE
            
    #     with self.assertRaises(AttributeError):
    #         self.will_message.retain = False

    def test_will_delay_interval_bounds(self):
        """Test will delay interval validation"""
        # Test negative delay interval
        with self.assertRaises(ValueError):
            WillMessage(
                topic="test/will",
                payload=b"test",
                qos=QoSLevel.AT_MOST_ONCE,
                retain=False,
                delay_interval=-1
            )
        
        # Test maximum delay interval (should be within uint32 bounds)
        max_delay = 4294967295  # 2^32 - 1
        will = WillMessage(
            topic="test/will",
            payload=b"test",
            qos=QoSLevel.AT_MOST_ONCE,
            retain=False,
            delay_interval=max_delay
        )
        self.assertEqual(will.delay_interval, max_delay)

    def test_topic_validation(self):
        """Test will message topic validation"""
        # Test empty topic
        with self.assertRaises(ValueError):
            WillMessage(
                topic="",
                payload=b"test",
                qos=QoSLevel.AT_MOST_ONCE,
                retain=False
            )
        
        # Test topic with wildcards (should not be allowed in will topics)
        with self.assertRaises(ValueError):
            WillMessage(
                topic="test/+/wildcard",
                payload=b"test",
                qos=QoSLevel.AT_MOST_ONCE,
                retain=False
            )
        
        with self.assertRaises(ValueError):
            WillMessage(
                topic="test/#",
                payload=b"test",
                qos=QoSLevel.AT_MOST_ONCE,
                retain=False
            )

class TestWillMessageTriggers(unittest.TestCase):
    """Test suite for will message trigger conditions"""

    @patch('src.connection.ConnectionHandler')
    def test_network_disconnection_trigger(self, mock_connection):
        """Test will message trigger on network disconnection"""
        will_message = WillMessage(
            topic="test/network/disconnect",
            payload=b"network disconnected",
            qos=QoSLevel.AT_LEAST_ONCE,
            retain=True
        )
        
        # Simulate network disconnection
        mock_connection.is_connected.return_value = False
        mock_connection.last_activity = None
        
        # Verify will message would be triggered
        self.assertTrue(mock_connection.should_send_will())
        self.assertEqual(mock_connection.will_message, will_message)

    @patch('src.connection.ConnectionHandler')
    def test_client_timeout_trigger(self, mock_connection):
        """Test will message trigger on client timeout"""
        will_message = WillMessage(
            topic="test/timeout",
            payload=b"client timeout",
            qos=QoSLevel.EXACTLY_ONCE,
            retain=False,
            delay_interval=30
        )
        
        # Simulate client timeout
        mock_connection.keepalive = 60
        mock_connection.last_activity = timedelta(seconds=90)
        
        # Verify will message would be triggered
        self.assertTrue(mock_connection.should_send_will())
        self.assertEqual(mock_connection.will_message, will_message)

    @patch('src.connection.ConnectionHandler')
    def test_clean_disconnect_handling(self, mock_connection):
        """Test will message handling during clean disconnect"""
        will_message = WillMessage(
            topic="test/clean/disconnect",
            payload=b"clean disconnect",
            qos=QoSLevel.AT_MOST_ONCE,
            retain=False
        )
        
        # Simulate clean disconnect
        mock_connection.disconnect(clean=True)
        
        # Verify will message should not be triggered
        self.assertFalse(mock_connection.should_send_will())

if __name__ == '__main__':
    """Run will message test suites"""
    suite = unittest.TestSuite()
    
    # Add test classes to suite
    # suite.addTest(TestWillMessageSetup("test_will_message_creation"))
    # suite.addTest(TestWillMessageSetup("test_will_message_default_values"))
    # suite.addTest(TestWillMessageSetup("test_will_message_payload_types"))
    # suite.addTest(TestWillMessageSetup("test_qos_level_validation"))

    # suite.addTest(TestWillMessageBehavior("test_will_message_immutability"))
    suite.addTest(TestWillMessageBehavior("test_will_delay_interval_bounds"))
    suite.addTest(TestWillMessageBehavior("test_topic_validation"))

    suite.addTest(TestWillMessageTriggers("test_network_disconnection_trigger"))
    # suite.addTest(TestWillMessageTriggers("test_client_timeout_trigger"))
    # suite.addTest(TestWillMessageTriggers("test_clean_disconnect_handling"))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite).wasSuccessful()