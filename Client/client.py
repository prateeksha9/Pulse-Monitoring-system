from flask import Flask, jsonify, render_template, request
import bluetooth
import threading
import queue
import time
import random
import json

app = Flask(__name__)

class BluetoothClient:
    def __init__(self, target_name, target_port, server_address):
        self.target_name = target_name
        self.server_address = server_address
        self.server_port = target_port
        self.client_socket = None
        self.data_thread = None
        self.data_thread_stop_event = threading.Event()
        self.command_queue = queue.Queue()  # Thread-safe queue for commands
        self.is_connected = False
        self.is_receiving_data = False
        self.pulse_data = None  # Store pulse data to send to the frontend

    def command_handler(self):
        """Process commands from the queue in a single thread."""
        while True:
            command = self.command_queue.get()  # Blocks until a command is available
            if command == "exit":
                print("Shutting down command handler.")
                self._handle_exit()
                break
            print(f"Processing command: {command}")
            if command == "connect":
                self._handle_connect()
            elif command == "start":
                self._handle_start()
            elif command == "stop":
                self._handle_stop()
            elif command == "disconnect":
                self._handle_disconnect()
            self.command_queue.task_done()  # Mark the task as done

    def queue_command(self, command):
        """Add a command to the queue."""
        self.command_queue.put(command)

    def _handle_connect(self):
        """Handle the connect command."""
        if not self.is_connected:
            if self.discover_and_pair():
                if self.connect_to_server():
                    print("Connection established.")
                else:
                    print("Failed to connect to the server.")
            else:
                print("Failed to pair with the server.")
        else:
            print("Already connected to the server.")

    def _handle_start(self):
        """Handle the start command."""
        if self.is_connected and not self.is_receiving_data:
            print("Starting handshake for data synchronization...")
            self.send_command("START_SYNC")
            response = self.receive_response()
            print(response)
            if response and "ACK" in response:
                self.send_command("ACK_ACK")
                self.start_data_reception()
            else:
                print("Failed to start data reception.")
        else:
            print("Either not connected or data reception already in progress.")

    def _handle_stop(self):
        """Handle the stop command."""
        if self.is_receiving_data:
            print("Stopping data reception...")
            self.send_command("STOP_SYNC")
            response = self.receive_response()
            if response and "ACK" in response:
                self.send_command("ACK_ACK")
                self.stop_data_reception()
            else:
                print("Failed to stop data reception.")
        else:
            print("Data reception is not active.")

    def _handle_disconnect(self):
        """Handle the disconnect command."""
        if self.is_connected:
            if self.is_receiving_data:
                self.stop_data_reception()
            self.close_connection()
            print("Disconnected from the server.")
        else:
            print("Not connected to any server.")

    def _handle_exit(self):
        """Handle the exit command."""
        print("Exiting client...")
        if self.is_connected:
            if self.is_receiving_data:
                self.stop_data_reception()
            self.close_connection()
        print("Client shut down.")

    def start(self):
        """Start the command handling thread."""
        self.command_thread = threading.Thread(target=self.command_handler, daemon=True)
        self.command_thread.start()

    # Bluetooth interaction methods
    def discover_and_pair(self):
        """Discover and pair with the target device."""
        if not self.server_address:
            print("Scanning for nearby Bluetooth devices...")
            nearby_devices = bluetooth.discover_devices(lookup_names=True)
            for addr, name in nearby_devices:
                if self.target_name.lower() in name.lower():
                    self.server_address = addr
                    print(f"Found server {name} at {addr}")
                    break
            if not self.server_address:
                print(f"Device named '{self.target_name}' not found.")
                return False
        print(f"Pairing is assumed successful. Proceeding to connect.")
        return True

    def connect_to_server(self):
        """Connect to the server."""
        if not self.server_address:
            print("Server address is not set. Ensure pairing is complete.")
            return False
        try:
            self.client_socket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            self.client_socket.connect((self.server_address, self.server_port))
            self.is_connected = True
            print("Connected to the server.")
            return True
        except bluetooth.BluetoothError as e:
            print(f"Failed to connect to the server: {e}")
            return False

    def send_command(self, command):
        """Send a command to the server."""
        if self.client_socket:
            try:
                self.client_socket.send(command)
                print(f"Sent command: {command}")
            except bluetooth.BluetoothError as e:
                print(f"Failed to send command: {e}")

    def receive_response(self, timeout=20):
        """Receive response from the server."""
        if self.client_socket:
            self.client_socket.settimeout(timeout)
            try:
                data = self.client_socket.recv(1024).decode("utf-8")
                print(f"Received: {data}")
                return data
            except bluetooth.BluetoothError:
                print("No response received within timeout.")
        return None

    def close_connection(self):
        """Close the Bluetooth connection."""
        if self.client_socket:
            self.client_socket.close()
            self.client_socket = None
            self.is_connected = False
            print("Disconnected from the server.")

    def start_data_reception(self):
        """Start receiving data in a separate thread."""
        print("Starting data reception...")
        self.data_thread_stop_event.clear()
        self.data_thread = threading.Thread(target=self.data_reception_loop, daemon=True)
        self.data_thread.start()
        self.is_receiving_data = True

    def data_reception_loop(self):
        """Threaded data reception loop."""
        while not self.data_thread_stop_event.is_set():
            data = self.receive_response(timeout=1000)
            if data:
                # data = {
                #                 "pulse": round(random.uniform(60, 100), 2),  # Random pulse value between 60 and 100
                #                 "impulses_per_minute": random.randint(50, 120),  # Random impulses per minute
                #                 "beats_per_minute": random.randint(50, 120),  # Random beats per minute
                #                 "root_mean_square": round(random.uniform(2.0, 5.0), 2),  # Random RMS value
                #                 "hrstd": round(random.uniform(0, 1), 2)  # Random heart rate standard deviation
                #              }

                pulse_data_json = json.loads(data)
                self.pulse_data = pulse_data_json
                # self.pulse_data = data  # Save pulse data to send to frontend
                print(f"Pulse Data: {self.pulse_data}")
            else:
                print("No data received or timeout occurred. Stopping reception.")
                self.stop_data_reception()
                break

    def stop_data_reception(self):
        """Stop receiving data."""
        print("Stopping data reception...")
        self.data_thread_stop_event.set()
        if self.data_thread:
            self.data_thread.join()
        self.is_receiving_data = False

    def get_pulse_data(self):
        """Return the latest pulse data."""
        return self.pulse_data
    
target_server_name = "IOT_Innovator_Server"
target_server_port = 1
target_server_address = "2C:CF:67:03:0E:1A"
bluetooth_client = BluetoothClient(target_server_name, target_server_port, target_server_address)
bluetooth_client.start()

# Route to serve the HTML page for the frontend
@app.route('/')
def index():
    return render_template('index.html')  # Ensure the file is in the templates folder

@app.route('/connect', methods=['POST'])
def connect():
    bluetooth_client.queue_command("connect")
    return jsonify({"status": "Connected to server"}), 200

@app.route('/disconnect', methods=['POST'])
def disconnect():
    bluetooth_client.queue_command("disconnect")
    return jsonify({"status": "Disconnected from server"}), 200

@app.route('/start', methods=['POST'])
def start():
    bluetooth_client.queue_command("start")
    return jsonify({"status": "Data reception started"}), 200

@app.route('/stop', methods=['POST'])
def stop():
    bluetooth_client.queue_command("stop")
    return jsonify({"status": "Data reception stopped"}), 200

@app.route('/get_pulse_data', methods=['GET'])
def get_pulse_data():
    if bluetooth_client.pulse_data:
        return jsonify({"pulsedata": bluetooth_client.pulse_data}), 200
    return jsonify({"pulsedata": None}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)