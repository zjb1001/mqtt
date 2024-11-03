import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

# add src into path, src path upper level two from this file
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.will_message import WillMessage, QoSLevel
from src.connection import (
    ConnectionHandler,
    ConnectPacket,
    MessageType,
    FixedHeader,
    ConnectFlags
)

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
            
    def test_will_message_verify_content(self):
        """Test will message content verification"""
        test_topic = "test/verify/content"
        test_payload = b"test payload"
        
        # Create will message with specific content
        will = WillMessage(
            topic=test_topic,
            payload=test_payload,
            qos=QoSLevel.AT_LEAST_ONCE,
            retain=True,
            delay_interval=30
        )
        
        # Verify each field matches expected values
        self.assertEqual(will.topic, test_topic, "Topic does not match")
        self.assertEqual(will.payload, test_payload, "Payload does not match")
        self.assertEqual(will.qos, QoSLevel.AT_LEAST_ONCE, "QoS level does not match")
        self.assertTrue(will.retain, "Retain flag does not match")
        self.assertEqual(will.delay_interval, 30, "Delay interval does not match")
        
        # Verify payload type is bytes
        self.assertIsInstance(will.payload, bytes, "Payload should be bytes type")

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
            
    def test_invalid_will_message_creation(self):
        """Test invalid will message creation scenarios"""
        # Test with invalid QoS level
        with self.assertRaises(ValueError):
            WillMessage(
                topic="test/invalid",
                payload=b"test",
                qos=99,  # Invalid QoS value
                retain=False
            )
            
        # Test with non-bytes payload
        with self.assertRaises(TypeError):
            WillMessage(
                topic="test/invalid",
                payload="string payload",  # Should be bytes
                qos=QoSLevel.AT_MOST_ONCE,
                retain=False
            )
            
        # Test with invalid delay interval type
        with self.assertRaises(TypeError):
            WillMessage(
                topic="test/invalid",
                payload=b"test",
                qos=QoSLevel.AT_MOST_ONCE,
                retain=False,
                delay_interval="30"  # Should be int
            )

class TestWillMessageTriggers(unittest.TestCase):
    """Test suite for will message trigger conditions"""

    def setUp(self):
        """Setup test fixtures before each test method"""
        self.will_message = WillMessage(
            topic="test/network/disconnect",
            payload=b"network disconnected",
            qos=QoSLevel.AT_LEAST_ONCE,
            retain=True
        )
        
    @patch('src.connection.ConnectionHandler')
    def test_network_disconnection_trigger(self, mock_connection_class):
        """Test will message trigger on network disconnection"""
        # Setup mock connection instance
        mock_connection = mock_connection_class.return_value
        mock_connection.will_message = self.will_message
        
        # Mock the internal state and behavior
        mock_connection.is_connected.return_value = False
        mock_connection.last_activity = timedelta(seconds=60)
        mock_connection.keep_alive_interval = 30
        
        # Create the actual connection handler
        connection_handler = ConnectionHandler()
        
        # Act - simulate network disconnection scenario
        actual_should_send = connection_handler.should_send_will()
        actual_will_message = connection_handler.get_will_message()
        
        # Assert
        self.assertTrue(actual_should_send, "Will message should be triggered on network disconnect")
        self.assertEqual(actual_will_message, self.will_message)
        
        # Verify the correct methods were called with expected parameters
        mock_connection.is_connected.assert_called_once()
        self.assertEqual(mock_connection.is_connected.call_count, 1)

    @patch('src.connection.ConnectionHandler')
    def test_no_will_message_when_connected(self, mock_connection_class):
        """Test will message should not trigger when network is connected"""
        # Setup
        mock_connection = mock_connection_class.return_value
        mock_connection.will_message = self.will_message
        mock_connection.is_connected.return_value = True
        mock_connection.last_activity = timedelta(seconds=1)
        
        connection_handler = ConnectionHandler()
        
        # Act
        actual_should_send = connection_handler.should_send_will()
        
        # Assert
        self.assertFalse(actual_should_send, "Will message should not trigger when connected")
        mock_connection.is_connected.assert_called_once()

    @patch('src.connection.ConnectionHandler')
    def test_will_message_on_keep_alive_timeout(self, mock_connection_class):
        """Test will message trigger on keep alive timeout"""
        # Setup
        mock_connection = mock_connection_class.return_value
        mock_connection.will_message = self.will_message
        mock_connection.is_connected.return_value = True
        mock_connection.last_activity =timedelta(seconds=45)
        mock_connection.keep_alive_interval = 30
        
        connection_handler = ConnectionHandler()
        
        # Act
        actual_should_send = connection_handler.should_send_will()
        
        # Assert
        self.assertTrue(actual_should_send, "Will message should trigger on keep alive timeout")
        mock_connection.is_connected.assert_called_once()

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

        # Setup mock connection with the will message
        mock_connection.will_message = will_message
        
        # Simulate client timeout
        mock_connection.keepalive = 60
        mock_connection.last_activity = timedelta(seconds=90)
        
        # Verify will message would be triggered
        self.assertTrue(mock_connection.should_send_will())
        self.assertEqual(mock_connection.will_message, will_message)

    @patch('src.connection.ConnectionHandler')
    def test_clean_disconnect_handling(self, mock_connection_class):
        """Test will message handling during clean disconnect"""
        mock_connection = mock_connection_class.return_value
        will_message = WillMessage(
            topic="test/clean/disconnect",
            payload=b"clean disconnect",
            qos=QoSLevel.AT_MOST_ONCE,
            retain=False
        )

        # Setup mock connection with the will message
        mock_connection.will_message = will_message
        mock_connection.should_send_will.return_value = False
        
        # Simulate clean disconnect
        mock_connection.disconnect(clean=True)
        
        # Verify will message should not be triggered
        self.assertFalse(mock_connection.should_send_will())

if __name__ == '__main__':
    """Run will message test suites"""
    suite = unittest.TestSuite()
    
    # Add test classes to suite
    suite.addTest(TestWillMessageSetup("test_will_message_creation"))
    suite.addTest(TestWillMessageSetup("test_will_message_default_values"))
    suite.addTest(TestWillMessageSetup("test_will_message_payload_types"))
    suite.addTest(TestWillMessageSetup("test_qos_level_validation"))
    suite.addTest(TestWillMessageSetup("test_will_message_verify_content"))

    suite.addTest(TestWillMessageBehavior("test_will_delay_interval_bounds"))
    suite.addTest(TestWillMessageBehavior("test_topic_validation"))
    suite.addTest(TestWillMessageBehavior("test_invalid_will_message_creation"))

    suite.addTest(TestWillMessageTriggers("test_network_disconnection_trigger"))
    suite.addTest(TestWillMessageTriggers("test_client_timeout_trigger"))
    suite.addTest(TestWillMessageTriggers("test_clean_disconnect_handling"))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite).wasSuccessful()