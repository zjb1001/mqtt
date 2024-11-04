import unittest
import asyncio
import time
import psutil
from unittest.mock import Mock, patch
from src.connection import ConnectionHandler
from src.publish import PublishHandler
from src.message_handler import MessageHandler
from src.session import SessionManager

class StressTestCase(unittest.TestCase):
    async def asyncSetUp(self):
        self.connection_handler = ConnectionHandler()
        self.publish_handler = PublishHandler()
        self.message_handler = MessageHandler()
        self.session_manager = SessionManager()
        
    def setUp(self):
        asyncio.run(self.asyncSetUp())

    def get_process_memory(self):
        """Helper to get current process memory usage"""
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024  # Convert to MB

    async def test_memory_constraints(self):
        """Test behavior under memory pressure"""
        # Arrange
        initial_memory = self.get_process_memory()
        large_messages = []
        
        # Act
        try:
            # Create increasingly large messages until memory limit
            for i in range(1000):
                message = Mock()
                message.payload = b"x" * (1024 * 1024)  # 1MB payload
                message.topic = f"test/topic/{i}"
                message.qos = 2
                large_messages.append(message)
                
                await self.message_handler.process_message(message)
                
                current_memory = self.get_process_memory()
                if current_memory - initial_memory > 1000:  # >1GB growth
                    break
                    
        except Exception as e:
            self.fail(f"Should handle memory pressure gracefully: {e}")
            
        # Assert
        final_memory = self.get_process_memory()
        self.assertLess(final_memory - initial_memory, 2000)  # Should not leak memory

    async def test_resource_exhaustion_recovery(self):
        """Test recovery after resource exhaustion"""
        # Arrange
        mock_clients = []
        for i in range(10000):
            client = Mock()
            client.client_id = f"stress_client_{i}"
            mock_clients.append(client)
            
        # Act - Phase 1: Create resource pressure
        try:
            tasks = [
                self.connection_handler.handle_connect(client)
                for client in mock_clients[:5000]  # Connect half
            ]
            await asyncio.gather(*tasks)
        except Exception:
            pass  # Expected to potentially fail
            
        # Act - Phase 2: Attempt recovery
        await asyncio.sleep(1)  # Allow time for cleanup
        
        recovery_clients = mock_clients[5000:]  # Try remaining clients
        success_count = 0
        
        for client in recovery_clients:
            try:
                await self.connection_handler.handle_connect(client)
                success_count += 1
            except Exception:
                continue
                
        # Assert
        self.assertGreater(success_count, 0)  # Should recover and accept new connections

    async def test_high_load_recovery(self):
        """Test system recovery under high load"""
        # Arrange
        message_count = 100000
        mock_message = Mock()
        mock_message.payload = b"test message"
        mock_message.topic = "test/topic"
        mock_message.qos = 1
        
        # Act - Phase 1: Generate high load
        tasks = []
        for _ in range(message_count):
            task = asyncio.create_task(
                self.message_handler.process_message(mock_message)
            )
            tasks.append(task)
            
        # Simulate network interruption
        await asyncio.sleep(0.1)
        for task in tasks[:len(tasks)//2]:
            task.cancel()
            
        # Act - Phase 2: Continue processing
        await asyncio.sleep(1)  # Allow recovery time
        
        # Try processing new messages
        new_messages = 1000
        success_count = 0
        
        for _ in range(new_messages):
            try:
                await self.message_handler.process_message(mock_message)
                success_count += 1
            except Exception:
                continue
                
        # Assert
        self.assertGreater(success_count / new_messages, 0.9)  # >90% success rate

if __name__ == '__main__':
    unittest.main()