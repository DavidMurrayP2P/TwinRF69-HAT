#!/usr/bin/env python3

import RFM69
from RFM69registers import *
import time
import RPi.GPIO as GPIO
import os
import fcntl
import struct
import subprocess
from typing import Optional, Union, IO
import errno

#You must set these two variables

REGION = 1 # Set to 1 for 433/915 and 2 for 433/868
NODE_ID = 1 #Set this to an integer between 0 and 9
OTHERNODE = 2
NETWORK_ID = 0
TOSLEEP = 0.01
TIMEOUT = 1

class RegionNotSetError(Exception):
    """Please set the appropriate region"""
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

def create_tun_for_node(node_id: int,
                        ifname: str = None,
                        network_base: str = "10.0.0",
                        prefix: int = 24):
    """
    Create a TUN device and assign it an IP based on node_id.
    Example: node_id=1 -> IP 10.0.0.1

    Parameters:
      node_id (int): Node id (1..254 recommended).
      ifname (str|None): Interface name to request (e.g. "tun0"). If None, defaults to "tun{node_id}".
      network_base (str): First three octets of network, e.g. "10.0.0".
      prefix (int): CIDR prefix length (default 24).
    
    Returns:
      tuple: (fileobj, ifname, ip_address) where fileobj is the opened /dev/net/tun file object.
    
    Raises:
      PermissionError: if not run as root.
      ValueError: if node_id out of expected range.
      CalledProcessError: if 'ip' commands fail.
    """

    if os.geteuid() != 0:
        raise PermissionError("create_tun_for_node must be run as root (or with CAP_NET_ADMIN)")

    if not (1 <= node_id <= 254):
        raise ValueError("node_id should be between 1 and 254")

    if ifname is None:
        ifname = f"tun{node_id}"

    ip_addr = f"{network_base}.{node_id}"
    cidr = f"{ip_addr}/{prefix}"

    # Open tun device
    TUN_DEVICE = "/dev/net/tun"
    tun = open(TUN_DEVICE, "r+b", buffering=0)

    # Constants for ioctl (Linux)
    IFF_TUN = 0x0001
    IFF_NO_PI = 0x1000
    # TUNSETIFF from <linux/if_tun.h>; common value on Linux x86_64
    TUNSETIFF = 0x400454ca

    # Prepare ifreq structure: 16-byte name + short flags (padding to 40 bytes)
    ifreq = struct.pack("16sH", ifname.encode("utf-8"), IFF_TUN | IFF_NO_PI)
    # ioctl to create/configure the interface
    fcntl.ioctl(tun, TUNSETIFF, ifreq)

    # Use iptool to assign address and bring interface up. Use 'replace' to avoid errors if already present.
    subprocess.check_call(["ip", "addr", "replace", cidr, "dev", ifname])
    subprocess.check_call(["ip", "link", "set", "dev", ifname, "up"])
    subprocess.check_call(["ip", "link", "set", "dev", ifname, "mtu", "256"])
    
    return tun, ifname, ip_addr

def read_tun_nonblocking(tun: Union[IO, int], bufsize: int = 4096) -> Optional[bytes]:
    """
    Non-blocking read from a TUN device.

    Parameters:
      tun: file-like object (opened /dev/net/tun) or integer file descriptor.
      bufsize: maximum number of bytes to read (default 4096).

    Returns:
      bytes containing the packet if available, otherwise None.

    Notes:
      - The function will set O_NONBLOCK on the file descriptor if it's not already set.
      - Caller must keep the tun file object open while using this function.
      - Typical usage: pass the file object returned by create_tun_for_node().
    """
    fd = tun.fileno() if hasattr(tun, "fileno") else int(tun)

    # Ensure non-blocking
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    if not (flags & os.O_NONBLOCK):
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    try:
        return os.read(fd, bufsize)
    except BlockingIOError:
        # No data available right now
        return None
    except OSError as e:
        if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
            return None
        raise

def chunk_and_print(packet: bytes, chunk_size: int = 60) -> None:
    """
    Split `packet` into chunks of `chunk_size` bytes and print each chunk's bytes as ints.

    Example output for one chunk: "Chunk 0: 10 255 0 34 ..."
    """
    if not isinstance(packet, (bytes, bytearray, memoryview)):
        raise TypeError("packet must be bytes, bytearray, or memoryview")

    mv = memoryview(packet)
    if len(mv) == 0:
        print("No data")
        return

    for i in range(0, len(mv), chunk_size):
        chunk = mv[i : i + chunk_size]
        ints = (str(b) for b in chunk.tobytes())
        print(f"Chunk {i // chunk_size}: " + " ".join(ints))

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

def receive_packet(OUTPUT_FILE, radio0, radio1, TOSLEEP, TIMEOUT):
    # Clear the contents of the output file
    open(OUTPUT_FILE, 'w').close()

    try:
        # Open the output file in binary append mode
        with open(OUTPUT_FILE, 'wb') as f:
            while True:
                #GPIO.output(led, GPIO.LOW)
                
                radio0.receiveBegin()
                radio1.receiveBegin()
                timedOut = 0
                while not ((radio1.receiveDone()) or (radio0.receiveDone())):
                    time.sleep(TOSLEEP)

                    if timedOut <= TIMEOUT:
                        #GPIO.output(led, GPIO.HIGH)
                        #sender = radio1.SENDERID
                        #sender = radio0.SENDERID

                        # Log the received data
                        if (radio0.RSSI < 0):
                            print(f"RX << {radio0.SENDERID}: (RSSI: {radio0.RSSI} {radio0.DATA}) 433MHz")
                            print("Checking for missing packets")
                            missing_packets = check_missing_packets(OUTPUT_FILE)
                            for missing_packet in missing_packets:
                                print(missing_packet)
                                send_ack(radio0, missing_packet)

                        if (radio1.RSSI < 0):
                            print(f"RX << {radio1.SENDERID}: (RSSI: {radio1.RSSI} {radio1.DATA}) 915MHz")

                        # Write the received data to the file
                        f.write(bytearray(radio1.DATA))
                        #f.write(bytearray(radio0.DATA))
                        f.flush()  # Ensure the data is written to disk immediately

                        # Process ACK if needed
                        #ackReq = radio1.ACKRequested()
                        #ackReq = radio0.ACKRequested()

                        #time.sleep(TIMEOUT / 2)

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

    tun_file, ifname, ip = create_tun_for_node(1)
    print(ifname, ip)

    try:

        radio0 = setup_radios(MODULE0, FREQUENCY0, NODE_ID, NETWORK_ID, 16, 15, 0, 0)
        radio1 = setup_radios(MODULE1, FREQUENCY1, NODE_ID, NETWORK_ID, 18, 22, 0, 1)

        neighbour_discovery(radio0)

        while True:

            pkt = read_tun_nonblocking(tun_file)
            if pkt is None:
                pass
            else:
                chunk_and_print(pkt)
                # ultimately send the packet
            
            # Display the menu options to the user
            #print("Please choose an option:")
            #print("1. Send a file")
            #print("2. Receive a file")

            # Read the user's response from the keyboard
            #response = input("Enter 1 or 2: ")

            # Check the user's response and perform the corresponding action
            #if response == '1':
            #    send_packet(file_path, chunk_size, radio0, radio1)

            #elif response == '2':
            #    receive_packet(OUTPUT_FILE, radio0, radio1, TOSLEEP, TIMEOUT)

            #else:
            #    print("Invalid input. Please enter 1 or 2.")

    except:
        print("Shutting down RFM69 modules")
        radio1.shutdown()
        radio0.shutdown()

if __name__ == "__main__":
    main()
