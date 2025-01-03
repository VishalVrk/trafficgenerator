from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import asyncio
import aiohttp
import random
import threading
import time
import uuid
from qos_manager import QoSManager

app = Flask(__name__)
socketio = SocketIO(app, async_mode="gevent")

# Define traffic types, user densities, and traffic loads
TRAFFIC_TYPES = {
    "Instagram": {"data_rate": 10.0, "latency": 20.0},
    "WhatsApp": {"data_rate": 1.0, "latency": 50.0},
    "YouTube": {"data_rate": 50.0, "latency": 15.0},
    "Voice Call": {"data_rate": 0.5, "latency": 10.0},
    "Text Message": {"data_rate": 0.01, "latency": 100.0},
    "Voice Message": {"data_rate": 5.0, "latency": 25.0},
}

# Initialize QoS Manager
qos_manager = QoSManager()

USER_DENSITIES = ["low", "medium", "high"]

# Store active tasks with their IDs
active_tasks = {}

def adjust_characteristics(characteristics, user_density):
    if user_density == "medium":
        characteristics["data_rate"] *= 0.75
        characteristics["latency"] *= 1.25
    elif user_density == "high":
        characteristics["data_rate"] *= 0.5
        characteristics["latency"] *= 1.5
    return characteristics

def generate_mock_data(user_density, traffic_type, stream_id):
    characteristics = TRAFFIC_TYPES[traffic_type].copy()
    characteristics = adjust_characteristics(characteristics, user_density)

    return {
        "stream_id": stream_id,
        "user_id": random.randint(0, 19),
        "data_rate": characteristics["data_rate"],
        "latency": characteristics["latency"],
        "packet_loss": random.uniform(0.0, 5.0),
        "traffic_load": random.choice(["light", "moderate", "heavy"]),
        "traffic_type": traffic_type,
        "cqi": random.uniform(0.1, 1.0)
    }

async def send_packets(user_density, traffic_type, stream_id):
    async with aiohttp.ClientSession() as session:
        while stream_id in active_tasks:
            raw_data = generate_mock_data(user_density, traffic_type, stream_id)
            
            # Apply QoS management
            processed_data = qos_manager.process_packet(stream_id, raw_data)
            
            try:
                async with session.post("http://127.0.0.1:5432/process_packet/", json=processed_data) as response:
                    if response.status == 200:
                        # Get QoS metrics
                        metrics = qos_manager.get_metrics(stream_id)
                        
                        socketio.emit("packet_status", {
                            "status": "sent",
                            "data": processed_data,
                            "metrics": metrics,
                            "stream_id": stream_id,
                            "qos_mode": qos_manager.qos_mode
                        })
                    else:
                        socketio.emit("packet_status", {
                            "status": "error",
                            "data": await response.text(),
                            "stream_id": stream_id
                        })
            except Exception as e:
                socketio.emit("packet_status", {
                    "status": "exception",
                    "data": str(e),
                    "stream_id": stream_id
                })
            await asyncio.sleep(1)

@app.route("/add_traffic_stream", methods=["POST"])
def add_traffic_stream():
    user_density = request.json.get("user_density")
    traffic_type = request.json.get("traffic_type")
    
    stream_id = str(uuid.uuid4())
    
    # Add stream to QoS manager
    qos_manager.add_stream(stream_id, traffic_type, user_density)
    
    # Create new background task for this stream
    active_tasks[stream_id] = {
        "thread": threading.Thread(
            target=lambda: asyncio.run(send_packets(user_density, traffic_type, stream_id))
        ),
        "traffic_type": traffic_type,
        "user_density": user_density
    }
    
    active_tasks[stream_id]["thread"].start()
    
    return jsonify({
        "status": "stream_started",
        "stream_id": stream_id,
        "traffic_type": traffic_type,
        "user_density": user_density
    })

@app.route("/remove_traffic_stream", methods=["POST"])
def remove_traffic_stream():
    stream_id = request.json.get("stream_id")
    
    if stream_id in active_tasks:
        # Remove stream from QoS manager
        qos_manager.remove_stream(stream_id)
        del active_tasks[stream_id]
        return jsonify({"status": "stream_stopped", "stream_id": stream_id})
    else:
        return jsonify({"error": "Stream not found"}), 404
    
@app.route("/switch_qos_mode", methods=["POST"])
def switch_qos_mode():
    new_mode = qos_manager.switch_qos_mode()
    return jsonify({"status": "success", "mode": new_mode})

@app.route("/get_active_streams", methods=["GET"])
def get_active_streams():
    return jsonify({
        stream_id: {
            "traffic_type": info["traffic_type"],
            "user_density": info["user_density"]
        }
        for stream_id, info in active_tasks.items()
    })

@app.route("/stop_all_streams", methods=["POST"])
def stop_all_streams():
    active_tasks.clear()
    return jsonify({"status": "all_streams_stopped"})

@app.route("/")
def index():
    return render_template("index.html", traffic_types=TRAFFIC_TYPES.keys(), user_densities=USER_DENSITIES)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5006)