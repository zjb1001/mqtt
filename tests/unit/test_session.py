import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

# add src into path, src path upper level two from this file
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.session import SessionState, QoSMessage
from src.will_message import QoSLevel

class TestSessionStateManagement(unittest.TestCase):
    """Test suite for MQTT session state management"""

    def setUp(self):
        """Set up test fixtures before each test method"""
        self.client_id = "test_client"
        self.session_state = SessionState(
            client_id=self.client_id,
            clean_session=True,
            subscriptions={},
            pending_messages={},
            timestamp=datetime.now()
        )

    def test_session_creation(self):
        """Test creating a new session with default values"""
        self.assertEqual(self.session_state.client_id, self.client_id)
        self.assertTrue(self.session_state.clean_session)
        self.assertEqual(len(self.session_state.subscriptions), 0)
        self.assertEqual(len(self.session_state.pending_messages), 0)
        self.assertIsInstance(self.session_state.timestamp, datetime)

    def test_persistent_session_creation(self):
        """Test creating a persistent session"""
        persistent_session = SessionState(
            client_id=self.client_id,
            clean_session=False,
            subscriptions={"test/topic": QoSLevel.AT_LEAST_ONCE},
            pending_messages={},
            timestamp=datetime.now()
        )
        
        self.assertFalse(persistent_session.clean_session)
        self.assertIn("test/topic", persistent_session.subscriptions)
        self.assertEqual(
            persistent_session.subscriptions["test/topic"],
            QoSLevel.AT_LEAST_ONCE
        )

    def test_subscription_management(self):
        """Test adding and updating subscriptions in session state"""
        # Add subscription
        self.session_state.subscriptions["test/topic"] = QoSLevel.AT_MOST_ONCE
        self.assertIn("test/topic", self.session_state.subscriptions)
        
        # Update subscription QoS
        self.session_state.subscriptions["test/topic"] = QoSLevel.EXACTLY_ONCE
        self.assertEqual(
            self.session_state.subscriptions["test/topic"],
            QoSLevel.EXACTLY_ONCE
        )
        
        # Multiple subscriptions
        self.session_state.subscriptions["test/topic2"] = QoSLevel.AT_LEAST_ONCE
        self.assertEqual(len(self.session_state.subscriptions), 2)

    def test_pending_message_management(self):
        """Test managing pending messages in session state"""
        # Create QoS message
        qos_message = QoSMessage(
            message_id=1,
            qos_level=QoSLevel.AT_LEAST_ONCE,
            timestamp=datetime.now()
        )
        
        # Add pending message
        self.session_state.pending_messages[1] = qos_message
        self.assertIn(1, self.session_state.pending_messages)
        
        # Update message state
        qos_message.state = "PUBREC_RECEIVED"
        self.assertEqual(
            self.session_state.pending_messages[1].state,
            "PUBREC_RECEIVED"
        )
        
        # Multiple pending messages
        qos_message2 = QoSMessage(
            message_id=2,
            qos_level=QoSLevel.EXACTLY_ONCE,
            timestamp=datetime.now()
        )
        self.session_state.pending_messages[2] = qos_message2
        self.assertEqual(len(self.session_state.pending_messages), 2)

class TestQoSMessageManagement(unittest.TestCase):
    """Test suite for QoS message handling within sessions"""

    def setUp(self):
        self.message = QoSMessage(
            message_id=1,
            qos_level=QoSLevel.AT_LEAST_ONCE,
            timestamp=datetime.now()
        )

    def test_qos_message_creation(self):
        """Test creating new QoS message"""
        self.assertEqual(self.message.message_id, 1)
        self.assertEqual(self.message.qos_level, QoSLevel.AT_LEAST_ONCE)
        self.assertEqual(self.message.retry_count, 0)
        self.assertEqual(self.message.state, "PENDING")
        self.assertFalse(self.message.ack_received)

    def test_qos_message_state_transitions(self):
        """Test QoS message state transitions"""
        # Initial state
        self.assertEqual(self.message.state, "PENDING")
        
        # Test complete QoS2 flow
        expected_states = [
            "PENDING",
            "PUBREC_RECEIVED",
            "PUBREL_SENT",
            "PUBCOMP_RECEIVED"
        ]
        
        for state in expected_states:
            self.message.state = state
            self.assertEqual(self.message.state, state)
        
        # Test acknowledgment
        self.message.ack_received = True
        self.assertTrue(self.message.ack_received)
        
        # Test timeout status
        self.message.timeout_occurred = True
        self.assertTrue(self.message.timeout_occurred)
        
        # Test message expiry
        original_timestamp = self.message.timestamp
        self.message.timestamp = datetime.now() - timedelta(hours=2)
        self.assertTrue(
            (datetime.now() - self.message.timestamp) > timedelta(hours=1)
        )

    def test_qos_message_retry_tracking(self):
        """Test tracking message retry attempts"""
        self.assertEqual(self.message.retry_count, 0)
        
        # Increment retry count
        self.message.retry_count += 1
        self.assertEqual(self.message.retry_count, 1)
        
        # Multiple retries
        self.message.retry_count += 2
        self.assertEqual(self.message.retry_count, 3)

class TestSessionStateOperations(unittest.TestCase):
    """Test suite for session state operations"""

    def setUp(self):
        self.session_state = SessionState(
            client_id="test_client",
            clean_session=False,
            subscriptions={},
            pending_messages={},
            timestamp=datetime.now()
        )
        
    def test_session_restoration(self):
        """Test restoring a persistent session"""
        # Create initial session with data
        original_session = SessionState(
            client_id="restore_test",
            clean_session=False,
            subscriptions={"test/topic": QoSLevel.AT_LEAST_ONCE},
            pending_messages={
                1: QoSMessage(
                    message_id=1,
                    qos_level=QoSLevel.AT_LEAST_ONCE,
                    timestamp=datetime.now()
                )
            },
            timestamp=datetime.now()
        )
        
        # Simulate session restoration
        restored_session = SessionState(
            client_id="restore_test",
            clean_session=False,
            subscriptions=original_session.subscriptions.copy(),
            pending_messages=original_session.pending_messages.copy(),
            timestamp=datetime.now()
        )
        
        # Verify restored session state
        self.assertEqual(restored_session.client_id, original_session.client_id)
        self.assertEqual(restored_session.subscriptions, original_session.subscriptions)
        self.assertEqual(
            len(restored_session.pending_messages),
            len(original_session.pending_messages)
        )
        self.assertFalse(restored_session.clean_session)

    def test_session_expiry(self):
        """Test session expiry determination"""
        # Create session with old timestamp
        old_session = SessionState(
            client_id="old_client",
            clean_session=False,
            subscriptions={},
            pending_messages={},
            timestamp=datetime.now() - timedelta(hours=2)
        )
        
        # Session should be considered expired
        session_expiry = timedelta(hours=1)
        self.assertTrue(
            (datetime.now() - old_session.timestamp) > session_expiry
        )

    def test_session_cleanup(self):
        """Test cleaning up session state"""
        # Add some test data
        self.session_state.subscriptions["test/topic"] = QoSLevel.AT_LEAST_ONCE
        self.session_state.pending_messages[1] = QoSMessage(
            message_id=1,
            qos_level=QoSLevel.AT_LEAST_ONCE,
            timestamp=datetime.now()
        )
        
        # Add expired message
        self.session_state.pending_messages[2] = QoSMessage(
            message_id=2,
            qos_level=QoSLevel.EXACTLY_ONCE,
            timestamp=datetime.now() - timedelta(hours=2)
        )
        
        # Add completed message
        completed_message = QoSMessage(
            message_id=3,
            qos_level=QoSLevel.AT_LEAST_ONCE,
            timestamp=datetime.now()
        )
        completed_message.ack_received = True
        self.session_state.pending_messages[3] = completed_message
        
        # Verify initial state
        self.assertEqual(len(self.session_state.subscriptions), 1)
        self.assertEqual(len(self.session_state.pending_messages), 3)
        
        # Clean expired messages
        expired_messages = [
            msg_id for msg_id, msg in self.session_state.pending_messages.items()
            if (datetime.now() - msg.timestamp) > timedelta(hours=1)
        ]
        for msg_id in expired_messages:
            del self.session_state.pending_messages[msg_id]
        
        # Clean completed messages
        completed_messages = [
            msg_id for msg_id, msg in self.session_state.pending_messages.items()
            if msg.ack_received
        ]
        for msg_id in completed_messages:
            del self.session_state.pending_messages[msg_id]
        
        # Verify cleanup of expired and completed messages
        self.assertEqual(len(self.session_state.pending_messages), 1)
        
        # Clear entire session
        self.session_state.subscriptions.clear()
        self.session_state.pending_messages.clear()
        
        # Verify complete cleanup
        self.assertEqual(len(self.session_state.subscriptions), 0)
        self.assertEqual(len(self.session_state.pending_messages), 0)

    def test_session_data_persistence(self):
        """Test session data persistence operations"""
        # Add test data
        self.session_state.subscriptions["test/topic"] = QoSLevel.AT_LEAST_ONCE
        qos_message = QoSMessage(
            message_id=1,
            qos_level=QoSLevel.AT_LEAST_ONCE,
            timestamp=datetime.now()
        )
        self.session_state.pending_messages[1] = qos_message
        
        # Verify data persistence
        serialized_data = {
            'client_id': self.session_state.client_id,
            'clean_session': self.session_state.clean_session,
            'subscriptions': self.session_state.subscriptions,
            'timestamp': self.session_state.timestamp.isoformat()
        }
        
        # Verify all required data is present
        self.assertIn('client_id', serialized_data)
        self.assertIn('clean_session', serialized_data)
        self.assertIn('subscriptions', serialized_data)
        self.assertIn('timestamp', serialized_data)
        
        # Verify data integrity
        self.assertEqual(serialized_data['client_id'], "test_client")
        self.assertFalse(serialized_data['clean_session'])
        self.assertIn("test/topic", serialized_data['subscriptions'])

if __name__ == '__main__':
    """Run session test suites"""
    suite = unittest.TestSuite()
    
    # Add test classes to suite
    suite.addTest(TestSessionStateManagement("test_session_creation"))
    suite.addTest(TestSessionStateManagement("test_persistent_session_creation"))
    suite.addTest(TestSessionStateManagement("test_subscription_management"))
    suite.addTest(TestSessionStateManagement("test_pending_message_management"))

    suite.addTest(TestQoSMessageManagement("test_qos_message_creation"))
    suite.addTest(TestQoSMessageManagement("test_qos_message_state_transitions"))
    suite.addTest(TestQoSMessageManagement("test_qos_message_retry_tracking"))
    
    suite.addTest(TestSessionStateOperations("test_session_restoration"))
    suite.addTest(TestSessionStateOperations("test_session_expiry"))
    suite.addTest(TestSessionStateOperations("test_session_cleanup"))
    suite.addTest(TestSessionStateOperations("test_session_data_persistence"))

    # Run the test suite
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)