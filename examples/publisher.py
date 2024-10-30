import asyncio
from datetime import datetime
from mqttProtocol.src import (
    ConnectionHandler, ConnectPacket, PublishHandler, 
    PublishPacket, QoSLevel, MessageHandler
)

async def run_publisher():
    # Create connection
    connect_packet = ConnectPacket(
        client_id="example_publisher",
        clean_session=True,
        keep_alive=60
    )
    
    # Initialize handlers
    connection_handler = ConnectionHandler()
    publish_handler = PublishHandler()
    message_handler = MessageHandler()
    
    # Start message handling
    await message_handler.start()
    
    # Publish messages with different QoS levels
    messages = [
        ("sensors/temperature", b"24.5", QoSLevel.AT_MOST_ONCE),
        ("sensors/humidity", b"65", QoSLevel.AT_LEAST_ONCE),
        ("sensors/pressure", b"1013", QoSLevel.EXACTLY_ONCE)
    ]
    
    for topic, payload, qos in messages:
        # Publish message
        packet_id = await publish_handler.publish_message(
            topic=topic,
            payload=payload,
            qos=qos,
            retain=False
        )
        
        print(f"Published message to {topic} with QoS {qos}")
        if packet_id:
            print(f"Packet ID: {packet_id}")
        
        # Small delay between messages
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(run_publisher())