import asyncio
from datetime import datetime
from mqttProtocol.src import (
    ConnectionHandler, ConnectPacket, PublishHandler,
    SubscriptionHandler, MessageHandler, SessionState,
    QoSLevel, WillMessage
)

async def setup_publisher(client_id: str):
    """Setup a publisher with will message"""
    will_message = WillMessage(
        topic="status/disconnected",
        payload=f"{client_id} disconnected".encode(),
        qos=QoSLevel.AT_LEAST_ONCE,
        retain=True
    )
    
    connect_packet = ConnectPacket(
        client_id=client_id,
        clean_session=True,
        keep_alive=60,
        will_message=will_message
    )
    
    connection_handler = ConnectionHandler()
    publish_handler = PublishHandler()
    
    return connection_handler, publish_handler

async def setup_subscriber(client_id: str):
    """Setup a subscriber with session state"""
    connect_packet = ConnectPacket(
        client_id=client_id,
        clean_session=False,  # Maintain session state
        keep_alive=60
    )
    
    session = SessionState(
        client_id=client_id,
        clean_session=False,
        subscriptions={},
        pending_messages={},
        timestamp=datetime.now()
    )
    
    connection_handler = ConnectionHandler()
    subscription_handler = SubscriptionHandler()
    subscription_handler.sessions[client_id] = session
    
    return connection_handler, subscription_handler, session

async def run_scenario():
    """Run a complete publish/subscribe scenario"""
    # Setup message handler
    message_handler = MessageHandler()
    await message_handler.start()
    
    # Setup publisher
    pub_conn, publisher = await setup_publisher("example_pub")
    
    # Setup subscriber
    sub_conn, subscriber, session = await setup_subscriber("example_sub")
    message_handler.sessions[session.client_id] = session
    
    # Subscribe to topics
    topics = [
        ("data/sensors/#", QoSLevel.AT_LEAST_ONCE),
        ("status/#", QoSLevel.AT_MOST_ONCE)
    ]
    
    for topic, qos in topics:
        subscriber._add_topic_node(
            subscriber._split_topic(topic),
            session.client_id,
            qos
        )
        session.subscriptions[topic] = qos
    
    # Publish some messages
    test_messages = [
        ("data/sensors/temp", b"23.5", QoSLevel.AT_LEAST_ONCE),
        ("data/sensors/humidity", b"68", QoSLevel.EXACTLY_ONCE),
        ("status/active", b"true", QoSLevel.AT_MOST_ONCE)
    ]
    
    for topic, payload, qos in test_messages:
        packet_id = await publisher.publish_message(topic, payload, qos)
        print(f"Published to {topic} with QoS {qos}")
        
        # Get matching subscribers
        matches = subscriber.get_matching_subscribers(topic)
        print(f"Matching subscribers for {topic}: {matches}")
        
        # Deliver to subscribers via message handler
        if matches:
            packet = PublishPacket(topic=topic, payload=payload, qos=qos)
            await message_handler._handle_publish(packet)
        
        await asyncio.sleep(0.5)
    
    # Check received messages
    print("\nReceived messages:")
    session_messages = message_handler.get_session_messages(session.client_id)
    for msg_id, msg in session_messages.items():
        print(f"Message {msg_id}: QoS {msg.qos_level}, State: {msg.state}")

if __name__ == "__main__":
    asyncio.run(run_scenario())