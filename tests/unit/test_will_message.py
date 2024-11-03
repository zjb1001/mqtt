import unittest
import asyncio
from datetime import timedelta, datetime
from unittest.mock import Mock, patch, AsyncMock, call

# add src into path, src path upper level two from this file
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.will_message import WillMessage, QoSLevel
from src.session import SessionState
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
        
    async def test_network_disconnection_trigger(self):
        """Test will message trigger on network disconnection"""
        # Setup connection handler with will message
        handler = ConnectionHandler()
        client_id = "test_client"
        
        # Create a mock StreamWriter
        mock_writer = Mock()
        mock_writer.close = Mock()
        mock_writer.wait_closed = AsyncMock()
        
        # Register client with will message
        handler.connections[client_id] = mock_writer
        handler.will_messages[client_id] = self.will_message
        
        # Mock message handler for will message verification
        handler.message_handler = Mock()
        handler.message_handler._handle_publish = AsyncMock()
        
        # Trigger unexpected disconnection
        await handler.handle_client_disconnect(client_id, unexpected=True)
        
        # Verify will message was processed
        self.assertIn(
            call._handle_publish.call_args[0][0].topic,
            self.will_message.topic,
            "Will message topic not matched"
        )
        self.assertIn(
            call._handle_publish.call_args[0][0].payload,
            self.will_message.payload,
            "Will message payload not matched"
        )
        
        # Verify connection cleanup
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_called_once()
        self.assertNotIn(client_id, handler.connections)
        self.assertNotIn(client_id, handler.will_messages)

    async def test_no_will_message_on_clean_disconnect(self):
        """Test will message should not trigger on clean disconnect"""
        # Setup connection handler
        handler = ConnectionHandler()
        client_id = "test_client"
        
        # Create a mock StreamWriter
        mock_writer = Mock()
        mock_writer.close = Mock()
        mock_writer.wait_closed = AsyncMock()
        
        # Register client with will message
        handler.connections[client_id] = mock_writer
        handler.will_messages[client_id] = self.will_message
        
        # Mock message handler
        handler.message_handler = Mock()
        handler.message_handler._handle_publish = AsyncMock()
        
        # Trigger clean disconnection
        await handler.handle_client_disconnect(client_id, unexpected=False)
        
        # Verify will message was not processed
        handler.message_handler._handle_publish.assert_not_called()
        
        # Verify connection cleanup still occurred
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_called_once()
        self.assertNotIn(client_id, handler.connections)

    async def test_will_message_on_keep_alive_timeout(self):
        """Test will message trigger on keep alive timeout"""
        # Setup connection handler
        handler = ConnectionHandler()
        client_id = "test_client"
        keep_alive = 2  # Short timeout for testing
        
        # Create a mock StreamWriter
        mock_writer = Mock()
        mock_writer.close = Mock()
        mock_writer.wait_closed = AsyncMock()
        
        # Register client with will message
        handler.connections[client_id] = mock_writer
        handler.will_messages[client_id] = self.will_message
        
        # Mock message handler
        handler.message_handler = Mock()
        handler.message_handler._handle_publish = AsyncMock()
        
        # Start keep-alive monitoring
        monitor_task = asyncio.create_task(
            handler._monitor_keep_alive(client_id, keep_alive)
        )
        
        # Wait for timeout and monitoring to complete
        await asyncio.sleep(keep_alive * 1.5 + 0.1)  # Wait slightly longer than timeout
        await monitor_task
        
        # Verify will message was processed
        handler.message_handler._handle_publish.assert_called_once()
        publish_packet = handler.message_handler._handle_publish.call_args[0][0]
        self.assertEqual(publish_packet.topic, self.will_message.topic)
        self.assertEqual(publish_packet.payload, self.will_message.payload)
        
        # Verify connection cleanup
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_called_once()
        self.assertNotIn(client_id, handler.connections)

    async def test_will_message_session_cleanup(self):
        """Test will message and session cleanup after disconnection"""
        # Setup connection handler
        handler = ConnectionHandler()
        client_id = "test_client"
        
        # Create session state
        handler.session_states[client_id] = SessionState(
            client_id=client_id,
            clean_session=True,
            subscriptions={},
            pending_messages={},
            timestamp=datetime.now()
        )
        
        # Create a mock StreamWriter
        mock_writer = Mock()
        mock_writer.close = Mock()
        mock_writer.wait_closed = AsyncMock()
        
        # Register client with will message
        handler.connections[client_id] = mock_writer
        handler.will_messages[client_id] = self.will_message
        
        # Mock message handler
        handler.message_handler = Mock()
        handler.message_handler._handle_publish = AsyncMock()
        
        # Trigger unexpected disconnection
        await handler.handle_client_disconnect(client_id, unexpected=True)
        
        # Verify complete cleanup
        self.assertNotIn(client_id, handler.connections)
        self.assertNotIn(client_id, handler.will_messages)
        self.assertNotIn(client_id, handler.session_states)

    async def test_will_message_with_retained_session(self):
        """Test will message handling with retained session state"""
        # Setup connection handler
        handler = ConnectionHandler()
        client_id = "test_client"
        
        # Create session state with clean_session=False
        handler.session_states[client_id] = SessionState(
            client_id=client_id,
            clean_session=False,  # Retained session
            subscriptions={},
            pending_messages={},
            timestamp=datetime.now()
        )
        
        # Create a mock StreamWriter
        mock_writer = Mock()
        mock_writer.close = Mock()
        mock_writer.wait_closed = AsyncMock()
        
        # Register client with will message
        handler.connections[client_id] = mock_writer
        handler.will_messages[client_id] = self.will_message
        
        # Mock message handler
        handler.message_handler = Mock()
        handler.message_handler._handle_publish = AsyncMock()
        
        # Trigger unexpected disconnection
        await handler.handle_client_disconnect(client_id, unexpected=True)
        
        # Verify will message processed but session retained
        handler.message_handler._handle_publish.assert_called_once()
        self.assertNotIn(client_id, handler.connections)
        self.assertNotIn(client_id, handler.will_messages)
        self.assertIn(client_id, handler.session_states)  # Session should be retained

if __name__ == '__main__':
    """Run will message test suites"""
    
    # Create event loop for async tests
    loop = asyncio.get_event_loop()
    
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

    # Add improved trigger tests
    suite.addTest(TestWillMessageTriggers("test_network_disconnection_trigger"))
    suite.addTest(TestWillMessageTriggers("test_no_will_message_on_clean_disconnect"))
    suite.addTest(TestWillMessageTriggers("test_will_message_on_keep_alive_timeout"))
    suite.addTest(TestWillMessageTriggers("test_will_message_session_cleanup"))
    suite.addTest(TestWillMessageTriggers("test_will_message_with_retained_session"))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Run async tests
    loop.run_until_complete(asyncio.gather(*[
        test._callTestMethod() 
        for test in suite._tests 
        if asyncio.iscoroutinefunction(getattr(test, test._testMethodName))
    ]))
    
    loop.close()