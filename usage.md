# MQTT Protocol Implementation Usage Guide

This guide provides an overview of how to use this MQTT protocol implementation and explores potential applications that can be built with it.

## Table of Contents
- [Basic Usage](#basic-usage)
- [Core Components](#core-components)
- [Example Applications](#example-applications)
- [Advanced Features](#advanced-features)
- [Development Guidelines](#development-guidelines)

## Basic Usage

### Installation
```python
# Clone the repository
git clone https://github.com/yourusername/mqttProtocol.git
cd mqttProtocol

# Install dependencies (if any)
pip install -r requirements.txt
```

### Creating a Basic MQTT Client
```python
from mqttProtocol import ConnectionHandler, PublishHandler, MessageHandler

async def main():
    # Initialize handlers
    connection = ConnectionHandler()
    message_handler = MessageHandler()
    
    # Start message handling
    await message_handler.start()
    
    # Connect to broker
    connect_packet = ConnectPacket(
        client_id="client-001",
        clean_session=True
    )
    
    # Publish a message
    await message_handler.publish_handler.publish_message(
        topic="sensors/temperature",
        payload=b"25.5",
        qos=QoSLevel.AT_LEAST_ONCE
    )

if __name__ == "__main__":
    asyncio.run(main())
```

## Core Components

### 1. Connection Management
- `ConnectionHandler`: Manages client connections and session states
- `ConnectPacket`: Handles MQTT CONNECT packet creation and parsing
- Features:
  - Clean session control
  - Keep-alive management
  - Will message support
  - Username/password authentication

### 2. Message Handling
- `MessageHandler`: Core message processing and routing
- `MessageQueue`: Message queuing and retained message storage
- Features:
  - QoS level support (0, 1, 2)
  - Retained message handling
  - Message acknowledgment
  - Inflight message tracking

### 3. Publishing
- `PublishHandler`: Manages message publishing
- Features:
  - QoS level support
  - Message retry mechanism
  - Packet ID management
  - DUP flag handling

### 4. Subscription
- `SubscriptionHandler`: Manages topic subscriptions
- Features:
  - Topic filtering
  - Wildcard support (+ and #)
  - QoS level matching
  - Subscription acknowledgment

## Example Applications

### 1. IoT Sensor Network
```python
# Example sensor data publisher
async def sensor_publisher():
    publisher = PublishHandler()
    while True:
        temperature = read_temperature()  # Your sensor reading function
        await publisher.publish_message(
            topic="home/living_room/temperature",
            payload=str(temperature).encode(),
            qos=QoSLevel.AT_LEAST_ONCE
        )
        await asyncio.sleep(60)  # Publish every minute
```

### 2. Chat Application
```python
# Example chat client
async def chat_client(client_id, room):
    connection = ConnectionHandler()
    message_handler = MessageHandler()
    
    # Subscribe to room
    await message_handler.subscription_handler.handle_subscribe(
        client_id,
        SubscribePacket(
            packet_id=1,
            topic_filters=[(f"chat/{room}/#", QoSLevel.EXACTLY_ONCE)]
        )
    )
    
    # Publish message
    await message_handler.publish_handler.publish_message(
        topic=f"chat/{room}/messages",
        payload="Hello, everyone!".encode(),
        qos=QoSLevel.EXACTLY_ONCE
    )
```

### 3. Home Automation System
```python
# Example smart home controller
async def home_automation():
    handler = MessageHandler()
    
    # Subscribe to device commands
    await handler.subscription_handler.handle_subscribe(
        "home-controller",
        SubscribePacket(
            packet_id=1,
            topic_filters=[
                ("home/+/lights/command", QoSLevel.AT_LEAST_ONCE),
                ("home/+/thermostat/command", QoSLevel.AT_LEAST_ONCE)
            ]
        )
    )
```

### 4. Fleet Management System
```python
# Example vehicle tracking system
async def fleet_tracker():
    handler = MessageHandler()
    publisher = PublishHandler()
    
    # Subscribe to all vehicle status updates
    await handler.subscription_handler.handle_subscribe(
        "fleet-manager",
        SubscribePacket(
            packet_id=1,
            topic_filters=[("fleet/+/status/#", QoSLevel.AT_LEAST_ONCE)]
        )
    )
    
    # Example of publishing vehicle location
    async def publish_vehicle_location(vehicle_id: str, lat: float, lon: float):
        payload = f"{lat},{lon}".encode()
        await publisher.publish_message(
            topic=f"fleet/{vehicle_id}/status/location",
            payload=payload,
            qos=QoSLevel.AT_LEAST_ONCE,
            retain=True  # Keep last known position
        )
```

### 5. Industrial Monitoring System
```python
# Example industrial sensor monitoring
async def factory_monitor():
    handler = MessageHandler()
    
    # Subscribe to machine metrics
    await handler.subscription_handler.handle_subscribe(
        "factory-monitor",
        SubscribePacket(
            packet_id=1,
            topic_filters=[
                ("factory/+/machine/+/temperature", QoSLevel.EXACTLY_ONCE),
                ("factory/+/machine/+/pressure", QoSLevel.EXACTLY_ONCE),
                ("factory/+/machine/+/status", QoSLevel.EXACTLY_ONCE)
            ]
        )
    )
    
    # Example alert publisher
    async def publish_alert(machine_id: str, alert_type: str, severity: str):
        payload = {
            "type": alert_type,
            "severity": severity,
            "timestamp": datetime.now().isoformat()
        }
        await handler.publish_handler.publish_message(
            topic=f"factory/alerts/machine/{machine_id}",
            payload=str(payload).encode(),
            qos=QoSLevel.EXACTLY_ONCE
        )
```

### 6. Healthcare Monitoring
```python
# Example patient monitoring system
async def patient_monitor():
    handler = MessageHandler()
    
    # Subscribe to patient vitals
    await handler.subscription_handler.handle_subscribe(
        "nurse-station",
        SubscribePacket(
            packet_id=1,
            topic_filters=[
                ("hospital/floor/+/room/+/vitals/#", QoSLevel.EXACTLY_ONCE),
                ("hospital/floor/+/room/+/alerts", QoSLevel.EXACTLY_ONCE)
            ]
        )
    )
    
    # Example vital signs publisher
    async def publish_vitals(floor: str, room: str, vital_type: str, value: float):
        await handler.publish_handler.publish_message(
            topic=f"hospital/floor/{floor}/room/{room}/vitals/{vital_type}",
            payload=str(value).encode(),
            qos=QoSLevel.EXACTLY_ONCE
        )
        
    # Example alert handler
    async def handle_critical_vital(vital_type: str, value: float, threshold: float):
        if value > threshold:
            await handler.publish_handler.publish_message(
                topic=f"hospital/alerts/critical/{vital_type}",
                payload=f"Critical {vital_type}: {value}".encode(),
                qos=QoSLevel.EXACTLY_ONCE,
                retain=True
            )
```

### 7. Environmental Monitoring System
```python
# Example environmental monitoring
async def env_monitor():
    handler = MessageHandler()
    
    # Subscribe to environmental sensors
    await handler.subscription_handler.handle_subscribe(
        "env-monitor",
        SubscribePacket(
            packet_id=1,
            topic_filters=[
                ("environment/+/air/quality/#", QoSLevel.AT_LEAST_ONCE),
                ("environment/+/water/quality/#", QoSLevel.AT_LEAST_ONCE),
                ("environment/+/soil/moisture", QoSLevel.AT_LEAST_ONCE)
            ]
        )
    )
    
    # Example data logger
    async def log_environmental_data(location: str, sensor_type: str, data: dict):
        await handler.publish_handler.publish_message(
            topic=f"environment/{location}/{sensor_type}",
            payload=str(data).encode(),
            qos=QoSLevel.AT_LEAST_ONCE,
            retain=True
        )
```

## Advanced Features

### 1. Will Messages
Will messages are sent automatically when a client disconnects unexpectedly:

```python
will_message = WillMessage(
    topic="status/device001",
    payload=b"offline",
    qos=QoSLevel.AT_LEAST_ONCE,
    retain=True
)

connect_packet = ConnectPacket(
    client_id="device001",
    clean_session=True,
    will_message=will_message
)
```

### 2. Retained Messages
Retained messages are stored and sent to new subscribers:

```python
await publish_handler.publish_message(
    topic="device/status",
    payload=b"active",
    qos=QoSLevel.AT_LEAST_ONCE,
    retain=True
)
```

### 3. QoS Levels
The protocol supports three QoS levels:
- QoS 0 (At most once)
- QoS 1 (At least once)
- QoS 2 (Exactly once)

## Development Guidelines

### Best Practices
1. **Error Handling**
   - Always handle connection errors
   - Implement retry mechanisms for failed messages
   - Log important events and errors

2. **Resource Management**
   - Clean up resources when closing connections
   - Monitor memory usage with large numbers of retained messages
   - Implement message expiry for retained messages

3. **Security**
   - Use TLS for secure connections
   - Implement proper authentication
   - Validate topic names and payloads

### Performance Optimization
1. **Message Queue**
   - Monitor queue size
   - Implement message prioritization if needed
   - Consider implementing message batching

2. **Subscription Tree**
   - Optimize topic matching algorithm
   - Consider caching frequently accessed topics
   - Monitor subscription tree depth

3. **Connection Handling**
   - Implement connection pooling for high-load scenarios
   - Monitor keep-alive intervals
   - Implement backoff strategies for reconnections

Remember to check the examples directory for more detailed implementation examples and test cases for guidance on specific use cases.

## Protocol Monitoring with Wireshark

Wireshark is a powerful tool for monitoring and debugging MQTT protocol communications. This section guides you through setting up and using Wireshark for MQTT protocol analysis.

### Setting Up Wireshark for MQTT

1. **Installation**
   - Download and install Wireshark from [wireshark.org](https://www.wireshark.org/)
   - MQTT protocol dissector is included by default in recent versions

2. **Capture Filter Setup**
   ```
   tcp port 1883 or tcp port 8883
   ```
   - 1883: Default MQTT port
   - 8883: Default MQTT over TLS port

3. **Display Filter Setup**
   ```
   mqtt
   ```
   - Shows only MQTT protocol packets
   - For specific message types: `mqtt.msgtype == 3` (PUBLISH messages)
   - For specific topics: `mqtt.topic contains "sensor"`

### Common MQTT Packet Analysis

1. **Connection Analysis**
   - Monitor CONNECT/CONNACK packets
   ```
   mqtt.msgtype == 1 or mqtt.msgtype == 2
   ```
   - Check client ID, clean session flag, and keep-alive value
   - Verify connection acceptance/rejection

2. **Publication Monitoring**
   - Track PUBLISH messages
   ```
   mqtt.msgtype == 3
   ```
   - Examine QoS levels: `mqtt.qos`
   - Check retained flag: `mqtt.retain`
   - View topic structure: `mqtt.topic`

3. **Subscription Tracking**
   - Monitor SUBSCRIBE/SUBACK
   ```
   mqtt.msgtype == 8 or mqtt.msgtype == 9
   ```
   - Verify topic filters
   - Check granted QoS levels

4. **QoS Flow Analysis**
   - Track message delivery for QoS 1 and 2
   ```
   mqtt.msgtype == 3 or mqtt.msgtype == 4 or mqtt.msgtype == 5
   ```
   - Follow packet IDs through the flow
   - Monitor retransmissions: `mqtt.dupflag == 1`

### Debugging Tips

1. **Connection Issues**
   - Look for TCP handshake completion
   - Check CONNECT packet parameters
   - Verify CONNACK response codes
   - Monitor keep-alive PINGREQ/PINGRESP

2. **Message Delivery Problems**
   - Track message flow with packet IDs
   - Check for missing ACKs
   - Monitor retransmissions
   - Verify QoS levels match expectations

3. **Performance Analysis**
   - Monitor packet timing
   - Check for delayed acknowledgments
   - Look for pattern in retransmissions
   - Analyze throughput using Wireshark statistics

4. **Troubleshooting Steps**
   ```
   # Check for connection issues
   mqtt.msgtype == 1 or mqtt.msgtype == 2

   # Monitor failed deliveries
   mqtt.msgtype == 3 and mqtt.dupflag == 1

   # Track specific client
   mqtt contains "client-id-here"

   # Monitor errors
   tcp.analysis.flags
   ```

### Example Analysis Scenarios

1. **Monitoring Message Flow**
   ```python
   # Start your application
   async def main():
       publisher = PublishHandler()
       await publisher.publish_message(
           topic="test/topic",
           payload=b"test message",
           qos=QoSLevel.EXACTLY_ONCE
       )

   # In Wireshark, use display filter:
   mqtt.topic == "test/topic"
   ```

2. **Debugging QoS 2 Flow**
   ```
   # Wireshark display filter for complete QoS 2 flow
   mqtt.msgtype == 3 or mqtt.msgtype == 5 or mqtt.msgtype == 6 or mqtt.msgtype == 7
   ```

3. **Session Analysis**
   ```
   # Monitor session establishment
   (mqtt.msgtype == 1 or mqtt.msgtype == 2) and mqtt.cleansess == 1
   ```

### Best Practices for Protocol Analysis

1. **Capture Setup**
   - Use appropriate capture and display filters
   - Save captures for later analysis
   - Document environmental conditions

2. **Analysis Process**
   - Start with broad filters and narrow down
   - Follow conversation flows
   - Look for patterns in timing and retransmissions

3. **Performance Monitoring**
   - Use Wireshark's built-in statistics tools
   - Monitor round-trip times
   - Track message rates and sizes

Remember to regularly capture and analyze traffic during development and testing phases to ensure protocol compliance and optimal performance.