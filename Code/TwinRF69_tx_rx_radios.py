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

    print("The node id is: " + str(node_id))

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

def send_packet(pkt: bytes, radio, OTHERNODE: int, chunk_size: int = 60, pause: float = 0.16) -> None:
    """
    Send the given pkt (bytes) over `radio` to `OTHERNODE` in chunks.

    Protocol:
      - Each payload = 4-byte header + chunk
      - Header = MSGID (uint16 BE), SEQ (uint16 BE)
      - SEQ 0..N-1 = data chunks
      - SEQ == 0xFFFF = END marker; its payload after header is two uint16 BE:
           total_chunks, orig_len

    This function will try to use a next_msg_id() function defined in the module (if present).
    If not found, it falls back to a time-based 16-bit msgid.
    The function attempts to send bytes; if radio.send rejects bytes it falls back to sending a list of ints.
    """

    if not isinstance(pkt, (bytes, bytearray)):
        raise TypeError("pkt must be bytes or bytearray")

    # obtain a msgid if a next_msg_id helper exists in this module
    msgid = None
    try:
        next_msg_fn = globals().get('next_msg_id')
        if callable(next_msg_fn):
            msgid = int(next_msg_fn()) & 0xFFFF
    except Exception:
        msgid = None

    if msgid is None:
        msgid = int(time.time() * 1000) & 0xFFFF

    total_len = len(pkt)
    total_chunks = (total_len + chunk_size - 1) // chunk_size

    try:
        for seq in range(total_chunks):
            start = seq * chunk_size
            chunk = pkt[start:start + chunk_size]
            header = struct.pack(">HH", msgid, seq)  # MSGID, SEQ
            payload = header + chunk

            # radio.send may accept bytes, strings, or list[int] depending on wrapper;
            # try bytes first, fallback to list of ints.
            try:
                radio.send(OTHERNODE, payload)
            except TypeError:
            #    print("Invalid input. Please enter 1 or 2.")
                radio.send(OTHERNODE, list(payload))

            print(f"TX >> {OTHERNODE}: msgid={msgid} seq={seq+1}/{total_chunks} chunk_len={len(chunk)}")
            time.sleep(pause)

        # send END marker with total_chunks and original length (both uint16 BE)
        end_header = struct.pack(">HH", msgid, 0xFFFF)
        end_payload = end_header + struct.pack(">HH", total_chunks & 0xFFFF, total_len & 0xFFFF)
        try:
            radio.send(OTHERNODE, end_payload)
        except TypeError:
            radio.send(OTHERNODE, list(end_payload))

        print(f"TX >> {OTHERNODE}: msgid={msgid} END total_chunks={total_chunks} orig_len={total_len}")

    except KeyboardInterrupt:
        # allow clean interruption
        print("send_packet: interrupted by user")
        raise
    except Exception as e:
        print(f"send_packet: error while sending: {e}")
        raise

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

    packet_size = 62

    tun_file, ifname, ip = create_tun_for_node(NODE_ID)
    print(ifname, ip)

    try:
        
        if NODE_ID == 0: 
            tx_radio = setup_radios(MODULE0, FREQUENCY0, NODE_ID, NETWORK_ID, 16, 15, 0, 0) 
            rx_radio = setup_radios(MODULE1, FREQUENCY1, NODE_ID, NETWORK_ID, 18, 22, 0, 1)
        if NODE_ID == 1:
            tx_radio = setup_radios(MODULE1, FREQUENCY1, NODE_ID, NETWORK_ID, 16, 15, 0, 0) 
            rx_radio = setup_radios(MODULE0, FREQUENCY0, NODE_ID, NETWORK_ID, 18, 22, 0, 1)

        while True:

            pkt = read_tun_nonblocking(tun_file)
            if pkt is None:
                pass
            else:
                send_packet(pkt, tx_radio, OTHERNODE, chunk_size=60)

    except:
        print("Shutting down RFM69 modules")
        tx_radio.shutdown()
        rx_radio.shutdown()

if __name__ == "__main__":
    main()
