#!/usr/bin/env python3

import RFM69
from RFM69registers import *
import time
import RPi.GPIO as GPIO
import socket
import struct
import binascii
import sys
import time
import os
import fcntl
import struct
import time

#You must set these two variables

REGION = 1 # Set to 1 for 433/915 and 2 for 433/868
NODE_ID = 2 #Set this to an integer between 0 and 9
OTHERNODE = 1
NETWORK_ID = 0
TOSLEEP = 0.01
TIMEOUT = 1

class RegionNotSetError(Exception):
    """Please set the appropriate region"""
    pass


def listen_tun_and_send(radio0, radio1, chunk_size, tun_name='tun0', stop_event=None):
    """
    Listen on the TUN device `tun_name`, for each IP packet read:
      - write the packet to a temporary file
      - call send_packet(temp_path, chunk_size, radio0, radio1)
      - remove the temporary file

    Parameters:
      radio0, radio1: your radio objects used by send_packet
      chunk_size: chunk size passed to send_packet (e.g. ~61)
      tun_name: name of the tun device (default 'tun0')
      stop_event: optional threading.Event; if set, loop terminates when stop_event.is_set()
    Notes:
      - The process must be able to open /dev/net/tun (typically run as root).
      - send_packet expects a file path; we write the tun packet to a temp file and pass that path.
    """
    import tempfile
    import errno

    # Ensure open_tun is available in this module (defined earlier)
    try:
        tun_fd = open_tun(tun_name)
    except Exception as e:
        print(f"listen_tun_and_send: failed to open TUN {tun_name}: {e}")
        return

    print(f"listen_tun_and_send: listening on {tun_name} (fd={tun_fd}). Press Ctrl+C to stop.")
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                print("listen_tun_and_send: stop_event set, exiting.")
                break

            try:
                # Read a single packet from the tun device.
                # 4096 is a typical MTU-sized buffer; adjust if you expect larger packets.
                packet = os.read(tun_fd, 4096)
            except OSError as e:
                # Non-fatal transient errors: try again
                if e.errno == errno.EINTR:
                    continue
                print(f"listen_tun_and_send: OSError while reading tun: {e}")
                break
            except Exception as e:
                print(f"listen_tun_and_send: unexpected error while reading tun: {e}")
                break

            if not packet:
                # Nothing read; continue
                time.sleep(0.01)
                continue

            # For debugging, show packet length & first bytes
            print(f"listen_tun_and_send: read packet {len(packet)} bytes from {tun_name}")

            # Write packet to a temporary file and call send_packet
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(delete=False) as tf:
                    tmp = tf.name
                    tf.write(packet)
                    tf.flush()
                print(f"listen_tun_and_send: wrote packet to temp file {tmp}, handing off to send_packet")
                # call user's send_packet function (already defined elsewhere in this file)
                send_packet(tmp, chunk_size, radio0, radio1)
                print(f"listen_tun_and_send: send_packet returned for {tmp}")
            except KeyboardInterrupt:
                print("listen_tun_and_send: interrupted by user")
                break
            except Exception as e:
                print(f"listen_tun_and_send: error while preparing/sending packet: {e}")
            finally:
                # Clean up temp file if it was created
                if tmp:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass

    except KeyboardInterrupt:
        print("listen_tun_and_send: interrupted by user (KeyboardInterrupt)")
    finally:
        try:
            os.close(tun_fd)
        except Exception:
            pass
        print("listen_tun_and_send: exit")

def listen_tun0(iface='tun0'):
    """
    Listen for packets on the specified interface (default 'tun0') and print basic details.

    Behaviour:
    - Tries to open a raw AF_PACKET socket and bind to the interface.
    - On each packet, attempts to detect/remove an Ethernet header (if present) and parse the IPv4 header.
    - Prints source/destination IP, protocol, packet length and a short hex preview.
    - Runs until KeyboardInterrupt (Ctrl-C) or an unrecoverable error occurs.

    Requirements:
    - Must be run as root or with CAP_NET_RAW.
    """
    try:
        s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0003))
        s.bind((iface, 0))
    except PermissionError:
        print("Permission denied: opening raw socket requires root (or CAP_NET_RAW). Run with sudo.")
        return
    except OSError as e:
        print(f"Could not bind to interface {iface}: {e}")
        return

    print(f"Listening on {iface} (press Ctrl-C to stop)...")
    try:
        while True:
            pkt, addr = s.recvfrom(65535)
            # Check for Ethernet header: bytes 12-13 == 0x0800 -> IPv4 Ethertype
            offset = 0
            if len(pkt) >= 14 and pkt[12:14] == b'\x08\x00':
                offset = 14

            # Ensure there's at least a minimal IP header
            if len(pkt) >= offset + 20:
                ip_header = pkt[offset:offset+20]
                try:
                    iph = struct.unpack('!BBHHHBBH4s4s', ip_header)
                    version_ihl = iph[0]
                    version = version_ihl >> 4
                    ihl = version_ihl & 0xF
                    iph_length = ihl * 4
                    src_ip = socket.inet_ntoa(iph[8])
                    dst_ip = socket.inet_ntoa(iph[9])
                    proto = iph[6]
                    print(f"[{time.strftime('%H:%M:%S')}] IP v{version} {src_ip} -> {dst_ip} proto={proto} pkt_len={len(pkt)}")
                    # print a short hex preview (first 64 bytes)
                    preview = binascii.hexlify(pkt[:64]).decode('ascii')
                    # group preview into readable chunks
                    grouped = ' '.join(preview[i:i+2] for i in range(0, min(len(preview), 128), 2))
                    print("  preview:", grouped)
                except struct.error:
                    print("  Received packet but failed to parse IP header; raw len:", len(pkt))
            else:
                # Not enough data for an IP header; just print raw preview
                preview = binascii.hexlify(pkt[:64]).decode('ascii')
                grouped = ' '.join(preview[i:i+2] for i in range(0, min(len(preview), 128), 2))
                print(f"[{time.strftime('%H:%M:%S')}] Raw pkt len={len(pkt)} preview: {grouped}")
    except KeyboardInterrupt:
        print("\nStopped listening on", iface)
    except Exception as exc:
        print("Error while listening:", exc)
    finally:
        try:
            s.close()
        except Exception:
            pass

def setup_radios(MODULE, FREQUENCY, NODE_ID, NETWORK_ID, INT_PIN, RST_PIN, SPI_BUS, SPI_DEV):

    # Initialize the 915MHz radio
    radio = RFM69.RFM69(
        freqBand=MODULE,  # Frequency band
        nodeID=NODE_ID,           # Node ID
        networkID=NETWORK_ID,         # Network ID
        isRFM69HW=True,        # High-power version flag
        intPin=INT_PIN,             # Custom interrupt pin
        rstPin=RST_PIN,             # Custom reset pin
        spiBus=SPI_BUS,              # Custom SPI bus
        spiDevice=SPI_DEV            # Custom SPI device
    )

    print("Class initialized")

    print("Reading all registers")
    results = radio.readAllRegs()
    for result in results:
        print(result)

    print("Performing rcCalibration")
    radio.rcCalibration()

    print("Setting high power")
    radio.setHighPower(True)
    radio.setPowerLevel(31)

    print("Checking temperature")
    print(radio.readTemperature(0))

    radio.setFrequency(FREQUENCY)
    radio.writeReg(REG_BITRATEMSB, RF_BITRATEMSB_250000)
    radio.writeReg(REG_BITRATELSB, RF_BITRATELSB_250000)
    radio.writeReg(REG_FDEVMSB, RF_FDEVMSB_50000)
    radio.writeReg(REG_FDEVLSB, RF_FDEVLSB_50000)

    return(radio)

def int_to_61_char_string(number):
    number_str = str(number)
    repeat_count = packet_size // len(number_str)
    remainder = packet_size % len(number_str)
    result = (number_str * repeat_count) + number_str[:remainder]
    result = result[:packet_size]
    return result

def divide_file_into_chunks(file_path, chunk_size):
    chunks = []
    try:
        with open(file_path, 'rb') as file:
            while True:
                chunk = file.read(chunk_size)
                if not chunk:
                    break
                chunks.append(chunk)
    except FileNotFoundError:
        print(f"The file {file_path} was not found.")
    except IOError as e:
        print(f"An error occurred: {e}")
    
    print(f"Total number of chunks: {len(chunks)}")
    return chunks

def neighbour_discovery(radio0):

    print("Searching for a neighbour")
    neighbour_discovered = False
    while (neighbour_discovered is False):
        # Broadcasting Node ID on control
        hello_msg = "%d\n" % (NODE_ID) 
        radio0.send(OTHERNODE, hello_msg) #Send without retrying for ack
        
        radio0.receiveBegin()
        start_time = time.time()
        timedOut = 0
        TIMEOUT_DURATION = 1
        while not (radio0.receiveDone()):
            time.sleep(TOSLEEP)

            elapsed_time = time.time() - start_time
            if elapsed_time > TIMEOUT_DURATION:
                #print(f"Timeout after {TIMEOUT_DURATION} seconds waiting for response.")
                break  # Exit the while loop after timeout

        # After exiting the loop, check if data was received
        if radio0.receiveDone():
            print(f"Received data: {radio0.DATA}")
            neighbour_discovered = True
            print("Neighbour discovery process completed.")
            radio0.send(OTHERNODE, hello_msg) #Send without retrying for ack

def check_missing_packets(OUTPUT_FILE): 

    print("We're going to check for missing packets")
    
    # Read the file and extract the second column values
    with open(OUTPUT_FILE, 'r') as file:
        received_numbers = [int(line.split(',')[1]) for line in file]

        if received_numbers:
            # The first and last sequence numbers
            first_seq = received_numbers[0]
            last_seq = received_numbers[-1]

            # Define the expected range of numbers from first_seq to last_seq
            expected_range = set(range(first_seq, last_seq + 1))
            # Convert received numbers to a set
            received_set = set(received_numbers)

            # Find the missing numbers
            missing_numbers = expected_range - received_set

            # Calculate the loss rate
            total_expected = len(expected_range)
            total_received = len(received_set)
            total_missing = len(missing_numbers)

            loss_rate = (total_missing / total_expected) * 100

            #print(f"Missing numbers: {sorted(missing_numbers)}")
            #print(f"Total expected packets: {total_expected}")
            #print(f"Total received packets: {total_received}")
            #print(f"Total missing packets: {total_missing}")
            #print(f"Packet loss rate: {loss_rate:.2f}%")

            return(missing_numbers)

def send_packet(file_path, chunk_size, radio0, radio1):

    chunks = divide_file_into_chunks(file_path, chunk_size)
    sequence = 0
    chunky = 1337

    try:
        for chunk in chunks:
            #msg = int_to_61_char_string(sequence)
            #msg = "%d, %d, %d\n" % (NODE, sequence, chunk)
            sequence += 1

            # Convert bytes to a list of integers
            data_as_list = list(chunk)
            msg = "%d, %d, %d\n" % (NODE_ID, sequence, chunky)

            radio1.send(OTHERNODE, msg)  # Send without retrying for ACK
            print("TX >> {OTHERNODE}: 915 {msg}")
            time.sleep(0.16)

        ack = "%d, %d, %d\n" % (NODE_ID, 99, 0)
        print("TX >> {OTHERNODE}: 433 {ack}")
        radio0.send(OTHERNODE, ack)  # Send without retrying for ACK
        time.sleep(0.16)

    except KeyboardInterrupt:
        # Clean up properly to not leave GPIO/SPI in an unusable state
        pass

def send_ack(radio0, missing_packet):

    try:
        msg = "%d, %d, %d\n" % (NODE_ID, missing_packet, chunky)

        radio0.send(OTHERNODE, msg)  # Send without retrying for ACK
        print("TX >> {OTHERNODE}: 433 {msg}")
        time.sleep(0.16)

    except KeyboardInterrupt:
        # Clean up properly to not leave GPIO/SPI in an unusable state
        pass

# TUN constants
TUN_DEVICE = "/dev/net/tun"
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000
# TUNSETIFF ioctl number for Linux (commonly used constant)
TUNSETIFF = 0x400454ca

def open_tun(name='tun0'):
    """
    Open /dev/net/tun and create a TUN device with the given name.
    Returns a file descriptor (integer) opened for reading/writing.
    """
    tun_fd = os.open(TUN_DEVICE, os.O_RDWR)
    ifr = struct.pack('16sH', name.encode('utf-8'), IFF_TUN | IFF_NO_PI)
    fcntl.ioctl(tun_fd, TUNSETIFF, ifr)
    # Note: Bringing the interface up / assigning addresses is left to the user / system.
    return tun_fd

def receive_packet(OUTPUT_FILE, radio0, radio1, TOSLEEP, TIMEOUT, tun_name='tun0'):
    """
    Read fragments from the radios, assemble into 256-byte IP packets
    and write them to a TUN device (tun_name). Falls back to writing
    to OUTPUT_FILE additionally for debugging if you keep that behavior.
    """
    # Buffer to hold incoming fragment bytes until we have 256 bytes to deliver
    buffer = bytearray()

    # Attempt to open the TUN device
    try:
        tun_fd = open_tun(tun_name)
    except Exception as e:
        print(f"Failed to open TUN device {tun_name}: {e}")
        print("Exiting receive loop.")
        return

    # Optionally keep the old OUTPUT_FILE writing for debugging (append binary)
    try:
        out_f = open(OUTPUT_FILE, 'wb')
        write_to_file = True
    except Exception:
        out_f = None
        write_to_file = False

    try:
        while True:
            radio0.receiveBegin()
            radio1.receiveBegin()
            timedOut = 0

            # Wait until either radio reports receiveDone
            while not (radio1.receiveDone() or radio0.receiveDone()):
                time.sleep(TOSLEEP)
                timedOut += TOSLEEP
                if timedOut > TIMEOUT:
                    # Timeout, break inner loop and restart receiveBegin cycle
                    break

            # If radio0 had a valid RSSI, log and check for missing packets
            if (hasattr(radio0, 'RSSI') and radio0.RSSI < 0):
                print(f"RX << {radio0.SENDERID}: (RSSI: {radio0.RSSI} {radio0.DATA}) 433MHz")
                print("Checking for missing packets")
                try:
                    missing_packets = check_missing_packets(OUTPUT_FILE)
                    for missing_packet in missing_packets:
                        print(f"Requesting missing packet: {missing_packet}")
                        send_ack(radio0, missing_packet)
                except Exception as e:
                    print(f"check_missing_packets failed: {e}")

            # If radio1 had a valid RSSI, log it
            if (hasattr(radio1, 'RSSI') and radio1.RSSI < 0):
                print(f"RX << {radio1.SENDERID}: (RSSI: {radio1.RSSI} {radio1.DATA}) 915MHz")

            # Acquire payload bytes from whichever radio completed
            # Prefer radio1 over radio0 if both set - adjust as needed
            payload = None
            if radio1.receiveDone():
                try:
                    payload = bytearray(radio1.DATA)
                except Exception:
                    # radio1.DATA might already be bytes or list of ints
                    try:
                        payload = bytes(radio1.DATA)
                    except Exception:
                        payload = None
            elif radio0.receiveDone():
                try:
                    payload = bytearray(radio0.DATA)
                except Exception:
                    try:
                        payload = bytes(radio0.DATA)
                    except Exception:
                        payload = None

            if payload:
                # Write raw payload to debug file if enabled
                if write_to_file:
                    try:
                        out_f.write(payload)
                        out_f.flush()
                    except Exception as e:
                        print(f"Warning: failed to write to OUTPUT_FILE: {e}")

                # Append payload to buffer and emit full 256-byte packets to TUN
                buffer.extend(payload)

                # Emit all complete 256-byte IP packets
                while len(buffer) >= 256:
                    ip_packet = bytes(buffer[:256])
                    try:
                        os.write(tun_fd, ip_packet)
                        print(f"WROTE 256 bytes to {tun_name}")
                    except Exception as e:
                        print(f"Failed to write to {tun_name}: {e}")
                        # If writing fails, we won't discard the bytes; break out to avoid data loss
                        break
                    # Remove emitted bytes from the buffer
                    del buffer[:256]

            # Short sleep to yield CPU, adjust as necessary
            time.sleep(TOSLEEP)

    except KeyboardInterrupt:
        # Handle program termination gracefully
        print("Interrupt received, shutting down...")
        check_missing_packets(OUTPUT_FILE)

    finally:
        # Cleanup GPIO and shutdown radio properly
        GPIO.output(led, GPIO.LOW)
        radio1.shutdown()
        radio0.shutdown()
        print("Shutdown complete")
        check_missing_packets(OUTPUT_FILE)

def main():

    if (REGION == 1):
        print("Entering 433MHz and 915MHz mode")
        MODULE1 = RF69_915MHZ
        FREQUENCY1 = 915000000
    elif (REGION == 2):
        print("Entering 433MHz and 868MHz mode")
        MODULE1 = RF69_868MHZ #Untested
        FREQUENCY1 = 868000000 #Untested
    else:
        raise RegionNotSetError("You have not defined a region. Exiting program.")

    # Constants for configuration
    MODULE0 = RF69_433MHZ
    FREQUENCY0 = 433000000

    OUTPUT_FILE = 'received_file.png'  # File to write received data
    file_path = 'logo.png'
    chunk_size = 60

    # Setup GPIO
    GPIO.setmode(GPIO.BOARD)
    led = 5
    GPIO.setup(led, GPIO.OUT)
    GPIO.output(led, GPIO.LOW)

    packet_size = 62

    try:

        radio0 = setup_radios(MODULE0, FREQUENCY0, NODE_ID, NETWORK_ID, 16, 15, 0, 0)
        radio1 = setup_radios(MODULE1, FREQUENCY1, NODE_ID, NETWORK_ID, 18, 22, 0, 1)

        neighbour_discovery(radio0)

        while True: 
            # Display the menu options to the user
            print("Please choose an option:")
            print("1. Send a file")
            print("2. Receive a file")
            print("3. Listen on tun0")

            # Read the user's response from the keyboard
            response = input("Enter 1 or 2: ")

            # Check the user's response and perform the corresponding action
            if response == '1':
                #send_packet(file_path, chunk_size, radio0, radio1)
                listen_tun_and_send(radio0, radio1, chunk_size, tun_name='tun0', stop_event=None)

            elif response == '2':
                receive_packet(OUTPUT_FILE, radio0, radio1, TOSLEEP, TIMEOUT)

            elif response == '3':
                listen_tun0('tun0')

            else:
                print("Invalid input. Please enter 1 or 2.")

    except:
        print("Shutting down RFM69 modules")
        radio1.shutdown()
        radio0.shutdown()

if __name__ == "__main__":
    main()


