import bluetooth
import threading
import json
import time
import subprocess

# ********************************* sensor ********************************
import max30102
import hrcalc

from collections import deque
import numpy as np
hrstd_queue = deque()
import random
from scipy.signal import butter, filtfilt, find_peaks
WINDOW_SIZE = 10
# Initialize the MAX30102 sensor
m = max30102.MAX30102()
# ********************************* sensor ********************************

class BluetoothConnectionManager:
    def __init__(self, on_connect_callback, on_disconnect_callback, on_data_received_callback, device_name="PiBluetoothServer"):
        self.server_socket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        self.server_socket.bind(("", bluetooth.PORT_ANY))
        self.server_socket.listen(1)
        self.client_socket = None
        self.client_address = None
        self.on_connect_callback = on_connect_callback
        self.on_disconnect_callback = on_disconnect_callback
        self.on_data_received_callback = on_data_received_callback

        # Set the Bluetooth device name
        self.set_device_name(device_name)
        
        # Automatically set discoverable and pairable
        self.set_discoverable()
        print("Bluetooth server initialized and waiting for client connection...")

        self.accept_thread = threading.Thread(target=self.accept_connection, daemon=True)
        self.accept_thread.start()

    def set_device_name(self, name):
        """Set the Bluetooth device name."""
        try:
            subprocess.run(["bluetoothctl", "system-alias", name], check=True)
            print(f"Bluetooth device name set to: {name}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to set Bluetooth device name: {e}")

    def set_discoverable(self):
        """Set the device as discoverable and pairable."""
        try:
            subprocess.run(["bluetoothctl", "discoverable", "on"], check=True)
            subprocess.run(["bluetoothctl", "pairable", "on"], check=True)
            print("Bluetooth is now discoverable and pairable.")
        except subprocess.CalledProcessError as e:
            print(f"Failed to set discoverable/pairable mode: {e}")

    def accept_connection(self):
        """Wait for a client to connect."""
        while True:
            try:
                print("Waiting for a new client to connect...")
                self.client_socket, self.client_address = self.server_socket.accept()
                print(f"New client connected: {self.client_address}")
                self.on_connect_callback()
                self.listen_for_data()
            except bluetooth.BluetoothError as e:
                print(f"Bluetooth error during connection: {e}")
            except Exception as e:
                print(f"Unexpected error: {e}")
            finally:
                # Ensure proper cleanup after disconnection
                if self.client_socket:
                    try:
                        self.client_socket.close()
                    except Exception as close_error:
                        print(f"Error closing client socket: {close_error}")
                self.client_socket = None
                self.client_address = None
                self.on_disconnect_callback()
                
                
    def listen_for_data(self):
        """Listen for data from the client."""
        while True:
            if self.client_socket:
                try:
                    data = self.client_socket.recv(1024).decode("utf-8").strip()
                    if data:
                        self.on_data_received_callback(data)
                except bluetooth.BluetoothError as e:
                    print(f"Bluetooth error: {e}")
                    self.on_disconnect_callback()
                    break

    def send_message(self, message):
        if self.client_socket:
            try:
                self.client_socket.send(message.encode())
            except bluetooth.BluetoothError as e:
                print(f"Failed to send message. Client may have disconnected: {e}")
                self.on_disconnect_callback()


class BluetoothPulseServer:
    def __init__(self):
        self.pulse_data = []
        self.stop_event = threading.Event()
        self.transmit_data = False
        self.ack_timeout = 20  # Timeout for receiving ACK_ACK
        self.pending_ack_ack = False
        self.ack_lock = threading.Lock()

        self.bluetooth_manager = BluetoothConnectionManager(
            on_connect_callback=self.start_data_collection,
            on_disconnect_callback=self.stop_data_collection,
            on_data_received_callback=self.data_received_callback,
            device_name="IOT_Innovator_Server"
        )
    def start_data_collection(self):
        print("Starting data collection")


    def stop_data_collection(self):
        print("Stopping data collection and transmission...")
        self.transmit_data = False
        self.stop_event.set()  # Stop any active threads
        # Safely close the client socket if open
        if self.bluetooth_manager.client_socket:
            try:
                self.bluetooth_manager.client_socket.close()
            except Exception as e:
                print(f"Error closing client socket: {e}")
        self.bluetooth_manager.client_socket = None
        self.bluetooth_manager.client_address = None
        # Reset stop event for future use
        self.stop_event.clear()
        print("Server is ready to accept a new client connection.")
    
    def wait_for_ack_ack(self, on_timeout=None):
        """Wait for ACK_ACK in a non-blocking way."""
        def wait():
            start_time = time.time()
            while time.time() - start_time < self.ack_timeout:
                time.sleep(0.1)  # Simulate non-busy wait
                with self.ack_lock:
                    if not self.pending_ack_ack:
                        print("ACK_ACK received. Exiting wait loop.")
                        return
            # Timeout logic
            print("Timeout waiting for ACK_ACK.")
            if on_timeout:
                on_timeout()

        # Start the wait in a separate thread
        threading.Thread(target=wait, daemon=True).start()

    def handle_start_sync_timeout(self):
        print("Failed to receive ACK_ACK for START_SYNC. Handshake failed.")
        self.pending_ack_ack = False
        self.transmit_data = False

    def handle_stop_sync_timeout(self):
        print("Failed to receive ACK_ACK for STOP_SYNC. Handshake failed.")
        self.pending_ack_ack = False
        self.transmit_data = True  # If STOP_SYNC fails, assume data transmission continues

    def data_received_callback(self, data):
        data = data.strip()
        print(f"Received data: {data}")

        if data == "START_SYNC":
            print("Received START_SYNC command from client.")
            self.bluetooth_manager.send_message("ACK")
            self.pending_ack_ack = True
            self.wait_for_ack_ack(on_timeout=self.handle_start_sync_timeout)

        elif data == "STOP_SYNC":
            print("Received STOP_SYNC command from client.")
            self.bluetooth_manager.send_message("ACK")
            self.pending_ack_ack = True
            self.wait_for_ack_ack(on_timeout=self.handle_stop_sync_timeout)

        elif data == "ACK_ACK":
            with self.ack_lock:
                if self.pending_ack_ack:
                    print("Received ACK_ACK from client.")
                    self.pending_ack_ack = False
                    # Check if we are handling START_SYNC or STOP_SYNC
                    if self.transmit_data:  # If data is currently being transmitted
                        print("Acknowledgment for STOP_SYNC received. Stopping data transmission.")
                        self.transmit_data = False  # Stop the transmission
                    else:  # Else, assume START_SYNC acknowledgment
                        print("Acknowledgment for START_SYNC received. Starting data transmission.")
                        self.transmit_data = True
                        self.start_pulse_data_stream()

    def start_pulse_data_stream(self):
        """Start a thread to continuously stream pulse data."""
        # threading.Thread(target=self.stream_pulse_data, daemon=True).start()

    def stream_pulse_data(self):
        """Stream pulse data continuously."""
        while 1:

                try:
                    pulse_data = self.read_sensor()
                    pulse_data_json = json.dumps(pulse_data)
                    if pulse_data_json and self.transmit_data:
                        print(f"Sending pulse data: {pulse_data_json}")
                        self.bluetooth_manager.send_message(pulse_data_json)
                    time.sleep(0.0010)
                except bluetooth.BluetoothError as e:
                    print(f"Bluetooth error during data transmission: {e}")
                    self.stop_data_collection()
                    break
                except Exception as e:
                    print(f"Unexpected error in data streaming: {e}")
                    self.stop_data_collection()
                    break
    def highpass_filter(self, data, cutoff, fs, order=5):
        """Apply a high-pass filter to remove the baseline drift."""
        nyquist = 0.5 * fs
        normal_cutoff = cutoff / nyquist
        b, a = butter(order, normal_cutoff, btype='high', analog=False)
        filtered_data = filtfilt(b, a, data)
        return filtered_data

    def lowpass_filter(self, data, cutoff, fs, order=5):
        """Apply a low-pass filter to remove high-frequency noise."""
        nyquist = 0.5 * fs
        normal_cutoff = cutoff / nyquist
        b, a = butter(order, normal_cutoff, btype='low', analog=False)
        filtered_data = filtfilt(b, a, data)
        return filtered_data

    def moving_average(self, data, window_size=5):
        """Apply a moving average filter for smoothing."""
        return np.convolve(data, np.ones(window_size) / window_size, mode='same')

    def preprocess_signal(self, ir_data, fs=100):
        """
        Preprocess the raw MAX30102 data by filtering and smoothing.
        
        Args:
            ir_data (array): Infrared data from MAX30102.
            fs (int): Sampling frequency in Hz.
            
        Returns:
            array: Processed infrared data.
        """
        # Filtering parameters
        high_cutoff = 0.5  # High-pass filter cutoff in Hz
        low_cutoff = 3.0   # Low-pass filter cutoff in Hz

        # High-pass filter (remove baseline drift)
        ir_filtered = self.highpass_filter(ir_data, high_cutoff, fs)

        # Low-pass filter (remove noise)
        ir_filtered = self.lowpass_filter(ir_filtered, low_cutoff, fs)

        # Smoothing
        ir_smoothed = self.moving_average(ir_filtered)

        return ir_smoothed
    def calculate_rmssd(self,rr_intervals):
        """
        Calculate Root Mean Square of the Successive Differences (RMSSD).
        Args:
            rr_intervals (np.array): RR intervals in seconds
        Returns:
            float: RMSSD
        """
        if len(rr_intervals) < 2:
            return None  # Not enough intervals to calculate RMSSD
        successive_diffs = np.diff(rr_intervals)
        rmssd = np.sqrt(np.mean(successive_diffs ** 2))
        return rmssd

    def detect_peaks(self, signal, fs):
        """
        Detect peaks in the processed signal and calculate BPM and IPM.
        
        Args:
            signal (array): Preprocessed signal.
            fs (int): Sampling frequency in Hz.
            
        Returns:
            tuple: Peaks, BPM, and IPM.
        """
        peaks, _ = find_peaks(signal, distance=fs//2)  # Assuming at least 0.5 seconds between peaks
        if len(peaks) > 1:
            rr_intervals = np.diff(peaks) * (1000 / fs)  # RR intervals in ms
            bpm = 60000 / np.mean(rr_intervals)  # Calculate BPM
            ipm = (len(peaks) / (len(signal) / fs)) * 60  # Calculate IPM
            rmssd = self.calculate_rmssd(rr_intervals)
        else:
            bpm = 0
            ipm = 0
            rmssd = 0
        return peaks, bpm, ipm, rmssd       
            
    def read_sensor(self):
        fs = 25
        for w in range(WINDOW_SIZE):
            # Read data from the sensor
            print("Read data from the sensor")
            red, raw_ir = m.read_sequential(100)

            # Calculate heart rate and SpO2
            processed_ir = self.preprocess_signal(raw_ir, fs)

            # Detect peaks and calculate metrics
            peaks, bpm, ipm, rmssd = self.detect_peaks(processed_ir, fs)

            hrstd_queue.append(bpm)

            if len(hrstd_queue) > 2 :
                hrstd = np.std(hrstd_queue)
            else:
                hrstd = None
            if len(hrstd_queue) > WINDOW_SIZE:
                hrstd_queue.popleft()
            

                pulse_data_json = {
                    "pulse": round(random.randint(60, 100), 2), # not in uses and not display
                    "impulses_per_minute": ipm,  
                    "beats_per_minute": bpm,  # this will display in chart
                    "root_mean_square": rmssd,  # Random RMS value //To Do: Aneri
                    "hrstd": hrstd  # Random heart rate standard deviation
                                }
                # print(f"Collected Data: {pulse_data_json}")
                return pulse_data_json
            else:
                print(f"hr_valid and and spo2_valid are invalid")
                return None
            
    
if __name__ == "__main__":
    pulse_server = BluetoothPulseServer()
    pulse_server.stream_pulse_data()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping server...")
    