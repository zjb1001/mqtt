import asyncio
from datetime import datetime
from mqttProtocol.src import (
    ConnectionHandler, ConnectPacket, SubscriptionHandler,
    SubscribePacket, QoSLevel, MessageHandler, SessionState
)

async def run_subscriber():
    # Create connection
    connect_packet = ConnectPacket(
        client_id="example_subscriber",
        clean_session=True,
        keep_alive=60
    )
    
    # Initialize handlers
    connection_handler = ConnectionHandler()
    subscription_handler = SubscriptionHandler()
    message_handler = MessageHandler()
    
    # Create session state
    session = SessionState(
        client_id="example_subscriber",
        clean_session=True,
        subscriptions={},
        pending_messages={},
        timestamp=datetime.now()
    )
    
    # Add session to handlers
    subscription_handler.sessions[session.client_id] = session
    message_handler.sessions[session.client_id] = session
    
    # Subscribe to topics
    subscriptions = [
        ("sensors/#", QoSLevel.AT_LEAST_ONCE),  # Wildcard subscription
        ("control/+/status", QoSLevel.EXACTLY_ONCE),  # Single-level wildcard
        ("system/alerts", QoSLevel.AT_MOST_ONCE)
    ]
    
    packet_id = 1  # In real implementation, this would be generated
    subscribe_packet = SubscribePacket(
        packet_id=packet_id,
        topic_filters=subscriptions
    )
    
    # Handle subscription
    return_codes = await subscription_handler.handle_subscribe(
        session.client_id, 
        subscribe_packet
    )
    
    print("Subscribed to topics:")
    for (topic, qos), code in zip(subscriptions, return_codes):
        print(f"Topic: {topic}, QoS: {qos}, Return Code: {code}")
    
    # Keep connection alive to receive messages
    try:
        while True:
            await asyncio.sleep(1)
            # Check for received messages
            messages = message_handler.get_session_messages(session.client_id)
            for msg_id, msg in messages.items():
                print(f"Received message {msg_id} with QoS {msg.qos_level}")
    except KeyboardInterrupt:
        print("\nSubscriber shutting down...")

if __name__ == "__main__":
    asyncio.run(run_subscriber())