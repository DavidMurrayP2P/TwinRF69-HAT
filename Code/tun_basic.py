#!/usr/bin/env python3

import os
import fcntl
import struct
import threading
import time
import sys
import select

# Constants for TUN interface
TUNSETIFF = 0x400454ca
IFF_TUN   = 0x0001
IFF_NO_PI = 0x1000

# Name of the TUN interface
TUN_DEVICE = 'tun0'

def open_tun_interface(tun_name=TUN_DEVICE):
    """
    Opens a TUN interface with the specified name.
    """
    # Open the clone device
    tun_fd = os.open('/dev/net/tun', os.O_RDWR)
    
    # Prepare the ioctl request
    ifr = struct.pack('16sH', tun_name.encode('utf-8'), IFF_TUN | IFF_NO_PI)
    
    # Issue the ioctl to create the TUN interface
    try:
        fcntl.ioctl(tun_fd, TUNSETIFF, ifr)
    except OSError as e:
        print(f"Failed to set up TUN interface {tun_name}: {e}")
        os.close(tun_fd)
        sys.exit(1)
    
    print(f"TUN interface '{tun_name}' opened successfully.")
    return tun_fd

def read_from_tun(tun_fd):
    """
    Continuously reads packets from the TUN interface and prints their details.
    """
    print("Starting to read packets from tun0...")
    while True:
        try:
            # Read up to 2048 bytes from the TUN interface
            packet = os.read(tun_fd, 2048)
            if packet:
                # For demonstration, print the packet length and raw data
                print(f"Received packet of length {len(packet)} bytes.")
                print(f"Packet Data: {packet.hex()}")  # Display in hexadecimal
        except OSError as e:
            print(f"Error reading from tun0: {e}")
            break

def write_to_tun(tun_fd):
    """
    Continuously writes dummy IP packets to the TUN interface at regular intervals.
    """
    print("Starting to write packets to tun0...")
    while True:
        try:
            # Create a simple IPv4 packet (Dummy data for demonstration)
            # This is not a valid packet; real IP packets should follow networking protocols
            dummy_packet = b'\x45\x00\x00\x28\xab\xcd\x40\x00\x40\x06\x7c\xbb\xc0\xa8\x01\x64\xc0\xa8\x01\xc8'
            # Modify the payload as needed for your application

            # Write the dummy packet to the TUN interface
            os.write(tun_fd, dummy_packet)
            print(f"Sent packet of length {len(dummy_packet)} bytes.")
            
            # Wait for 5 seconds before sending the next packet
            time.sleep(5)
        except OSError as e:
            print(f"Error writing to tun0: {e}")
            break

def main():
    # Open the TUN interface
    tun_fd = open_tun_interface(TUN_DEVICE)
    
    # Create threads for reading and writing
    read_thread = threading.Thread(target=read_from_tun, args=(tun_fd,), daemon=True)
    write_thread = threading.Thread(target=write_to_tun, args=(tun_fd,), daemon=True)
    
    # Start the threads
    read_thread.start()
    write_thread.start()
    
    print("TUN interface read and write threads started.")
    print("Press Ctrl+C to exit.")
    
    try:
        while True:
            # Keep the main thread alive
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...")
    finally:
        os.close(tun_fd)
        print("TUN interface closed.")

if __name__ == "__main__":
    main()

