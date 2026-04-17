#!/usr/bin/env python3

import RFM69
from RFM69registers import *
import time
import RPi.GPIO as GPIO
import os
import fcntl
import select
import struct
import subprocess
from typing import Optional, Union, IO
import errno

#You must set these two variables

REGION = 1 # Set to 1 for 433/915 and 2 for 433/868
NODE_ID = 1 #Set this to an integer between 0 and 9
OTHERNODE = 2
NETWORK_ID = 0
TOSLEEP = 0.005
TIMEOUT = 1

_rx_buffers = {}
_rx_timestamps = {}

class RegionNotSetError(Exception):
    """Please set the appropriate region"""
    pass

def setup_radios(MODULE, FREQUENCY, NODE_ID, NETWORK_ID, INT_PIN, RST_PIN, SPI_BUS, SPI_DEV):

    radio = RFM69.RFM69(
        freqBand=MODULE,
        nodeID=NODE_ID,
        networkID=NETWORK_ID,
        isRFM69HW=True,
        intPin=INT_PIN,
        rstPin=RST_PIN,
        spiBus=SPI_BUS,
        spiDevice=SPI_DEV
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

    # Accept packets addressed to any node ID — needed so the TX radio can
    # receive ACK frames that may be addressed to the remote node's ID.
    radio.promiscuous(True)

    radio.setFrequency(FREQUENCY)

    # Bitrate: 250 kbps
    radio.writeReg(REG_BITRATEMSB, RF_BITRATEMSB_250000)
    radio.writeReg(REG_BITRATELSB, RF_BITRATELSB_250000)

    # FIX 1 — Gaussian BT=0.5 shaping: tightens TX spectrum, improves sensitivity ~1-2 dB.
    # Was RF_DATAMODUL_MODULATIONSHAPING_00 (no shaping).
    radio.writeReg(REG_DATAMODUL,
                   RF_DATAMODUL_DATAMODE_PACKET |
                   RF_DATAMODUL_MODULATIONTYPE_FSK |
                   RF_DATAMODUL_MODULATIONSHAPING_01)

    # FIX 2 — Fdev = 75 kHz: modulation index h = 2*75k/250k = 0.6 (must be >= 0.5).
    # Previous RF_FDEVMSB/LSB_50000 gave h=0.4 — too low, partial eye closure.
    # 75000 Hz / 61.03515625 Hz/step = 0x04D0
    radio.writeReg(REG_FDEVMSB, 0x04)
    radio.writeReg(REG_FDEVLSB, 0xD0)

    # FIX 3 — RxBw = 200 kHz: must satisfy RxBw >= Fdev + BitRate/2 = 75k + 125k = 200 kHz.
    # Library default was MANT_16|EXP_2 = 125 kHz — too narrow, the main cause of
    # constant CRC failures and corrupted packets.
    # MANT_20|EXP_1 -> 32e6 / (20 * 2 * 4) = 200 kHz.
    radio.writeReg(REG_RXBW,
                   RF_RXBW_DCCFREQ_010 |
                   RF_RXBW_MANT_20 |
                   RF_RXBW_EXP_1)

    # FIX 4 — AfcBw = 400 kHz: AFC bandwidth must be wider than RxBw to lock on
    # during the preamble. Was never set — defaulted to ~83 kHz, causing the AFC
    # to pull the LO the wrong direction on weak signals.
    # MANT_20|EXP_0 -> 32e6 / (20 * 1 * 4) = 400 kHz.
    # REG_AFCBW = 0x1A
    radio.writeReg(0x1A,
                   RF_RXBW_DCCFREQ_010 |
                   RF_RXBW_MANT_20 |
                   RF_RXBW_EXP_0)

    # FIX 5 — DC-free whitening: prevents long 0/1 runs from drifting the receiver's
    # DC baseline at 250 kbps. Was DCFREE_OFF.
    radio.writeReg(REG_PACKETCONFIG1,
                   RF_PACKET1_FORMAT_VARIABLE |
                   RF_PACKET1_DCFREE_WHITENING |
                   RF_PACKET1_CRC_ON |
                   RF_PACKET1_CRCAUTOCLEAR_ON |
                   RF_PACKET1_ADRSFILTERING_OFF)

    # Arm the receiver
    radio.receiveBegin()

    print(f"Radio ready: freq={FREQUENCY/1e6:.3f}MHz  Fdev=75kHz  RxBw=200kHz  AfcBw=400kHz  BR=250kbps")

    return radio

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
    subprocess.check_call(["ip", "link", "set", "dev", ifname, "mtu", "120"])
    
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

def send_packet(pkt: bytes, radio, OTHERNODE: int, chunk_size: int = 55, pause: float = TOSLEEP, rx_radio=None) -> None:
    """
    Send the given pkt (bytes) over `radio` to `OTHERNODE` in chunks.

    Protocol:
      - Each payload = 4-byte header + chunk
      - Header = MSGID (uint16 BE), SEQ (uint16 BE)
      - SEQ 1..N = data chunks (starts at 1, not 0, to avoid RFM69 dropping first packet)
      - SEQ == 0xFFFE = XOR parity chunk (FEC); allows recovery of any single lost data chunk.
      - SEQ == 0xFFFF = END marker; its payload after header is two uint16 BE:
           total_chunks, orig_len

    The parity chunk is the byte-wise XOR of all data chunks (shorter chunks are
    zero-padded to chunk_size before XORing).  The receiver can reconstruct any one
    missing data chunk as: missing = parity XOR (XOR of all other received chunks),
    then truncated back to the correct length using orig_len.

    Parameters:
      rx_radio: If provided, this radio is muted to standby immediately before each
                frame is transmitted and re-armed after TX completes.  Use this when
                the TX and RX radios are physically close to each other (e.g. on the
                same HAT) so that the TX burst cannot desensitise the RX front-end
                and cause the RX radio to miss the chunk from the remote side that
                arrives simultaneously.  Has no effect when rx_radio=None.
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

    def _radio_send(payload):
        if rx_radio is not None:
            rx_radio.setMode(RF69_MODE_STANDBY)
        try:
            radio.send(OTHERNODE, payload)
        except TypeError:
            radio.send(OTHERNODE, list(payload))
        if rx_radio is not None:
            rx_radio.receiveBegin()
        time.sleep(pause)

    try:
        # Build and send all data chunks; accumulate XOR parity as we go.
        parity = bytearray(chunk_size)
        for seq in range(total_chunks):
            start = seq * chunk_size
            chunk = pkt[start:start + chunk_size]
            # XOR chunk into parity (zero-pad short final chunk)
            padded = chunk.ljust(chunk_size, b'\x00')
            for i in range(chunk_size):
                parity[i] ^= padded[i]

            actual_seq = seq + 1  # SEQ starts at 1, not 0
            header = struct.pack(">HH", msgid, actual_seq)
            _radio_send(header + chunk)
            print(f"TX > {OTHERNODE}: msgid={msgid} seq={actual_seq}/{total_chunks} chunk_len={len(chunk)}")

        # Send FEC parity chunk (seq=0xFFFE)
        parity_header = struct.pack(">HH", msgid, 0xFFFE)
        _radio_send(parity_header + bytes(parity))
        print(f"TX > {OTHERNODE}: msgid={msgid} PARITY chunk_len={chunk_size}")

        # Send END marker (seq=0xFFFF)
        end_header = struct.pack(">HH", msgid, 0xFFFF)
        end_payload = end_header + struct.pack(">HH", total_chunks & 0xFFFF, total_len & 0xFFFF)
        _radio_send(end_payload)
        print(f"TX > {OTHERNODE}: msgid={msgid} END total_chunks={total_chunks} orig_len={total_len}")

    except KeyboardInterrupt:
        print("send_packet: interrupted by user")
        raise
    except Exception as e:
        print(f"send_packet: error while sending: {e}")
        raise

_rx_parity = {}  # (sender_id, msgid) -> bytearray of received parity chunk

def receive_packet_reassemble(radio_rx):
    """
    Non-blocking receive that reassembles fragmented packets.
    Returns (sender_id, reassembled_bytes) when complete, otherwise None.

    FEC (Forward Error Correction):
      The sender transmits an XOR parity chunk (seq=0xFFFE) after all data chunks.
      If exactly one data chunk is missing when the END marker arrives, the receiver
      reconstructs it as:  missing = parity XOR (XOR of all other received chunks).
      This corrects any single lost chunk per message at the cost of one extra radio
      frame per packet.
    """
    global _rx_buffers, _rx_timestamps, _rx_parity
    
    if not radio_rx.receiveDone():
        return None
    
    # Snapshot radio state into locals before any slow processing.
    sender_id = radio_rx.SENDERID
    rssi = radio_rx.RSSI
    data = radio_rx.DATA

    if isinstance(data, (list, tuple)):
        data_bytes = bytes(data)
    else:
        data_bytes = data
    
    print(f"[RX RAW] {sender_id}: RSSI={rssi} raw_len={len(data_bytes)}")
    
    if len(data_bytes) < 4:
        return None
    
    try:
        msgid, seq = struct.unpack(">HH", data_bytes[:4])
        chunk = data_bytes[4:]
    except Exception as e:
        print(f"[RX ERROR] Failed to parse header: {e}")
        return None

    # Reject packets whose sequence number is impossible for this protocol.
    # Valid data chunks have seq in 1..255; parity uses 0xFFFE; END uses 0xFFFF.
    # Ghost/corrupt packets that slip past the hardware CRC consistently show
    # seq == msgid at values like 2827, 8738, or 16448 — far outside this range.
    if seq not in (0xFFFE, 0xFFFF) and (seq == 0 or seq > 255):
        print(f"[RX DISCARD] {sender_id}: msgid={msgid} seq={seq} out of range, discarding")
        return None

    current_time = time.time()
    msg_key = (sender_id, msgid)
    
    # Clean up old messages (data buffers and parity)
    expired_keys = [key for key, ts in _rx_timestamps.items() if current_time - ts > 10.0]
    for key in expired_keys:
        _rx_buffers.pop(key, None)
        _rx_timestamps.pop(key, None)
        _rx_parity.pop(key, None)
    
    if msg_key not in _rx_buffers:
        _rx_buffers[msg_key] = {}
        _rx_timestamps[msg_key] = current_time

    if seq == 0xFFFE:
        # FEC parity chunk
        _rx_parity[msg_key] = bytearray(chunk)
        print(f"[RX PARITY] {sender_id}: msgid={msgid} parity_len={len(chunk)}")
        return None

    if seq == 0xFFFF:
        # END marker received
        print(f"[RX END] {sender_id}: msgid={msgid}")
        
        if len(chunk) < 4:
            _rx_buffers.pop(msg_key, None)
            _rx_timestamps.pop(msg_key, None)
            _rx_parity.pop(msg_key, None)
            return None
        
        try:
            total_chunks, orig_len = struct.unpack(">HH", chunk[:4])
        except Exception:
            _rx_buffers.pop(msg_key, None)
            _rx_timestamps.pop(msg_key, None)
            _rx_parity.pop(msg_key, None)
            return None
        
        buf = _rx_buffers[msg_key]
        chunks_received = len(buf)
        received_seqs = sorted(buf.keys())
        
        print(f"[RX DEBUG] {sender_id}: msgid={msgid} received {chunks_received}/{total_chunks} chunks: {received_seqs}")
        
        if chunks_received == total_chunks - 1 and msg_key in _rx_parity:
            # Exactly one data chunk is missing — attempt FEC recovery.
            missing_seq = next((i for i in range(1, total_chunks + 1) if i not in buf), None)
            if missing_seq is not None:
                parity = bytearray(_rx_parity[msg_key])
                parity_len = len(parity)
                # XOR parity with every received chunk (zero-padded to parity_len)
                for s, c in buf.items():
                    padded = c.ljust(parity_len, b'\x00')
                    for i in range(parity_len):
                        parity[i] ^= padded[i]
                # parity now holds the recovered missing chunk; truncate the final
                # chunk to its correct length so reassembly[:orig_len] stays exact.
                if missing_seq == total_chunks:
                    last_chunk_len = orig_len - (total_chunks - 1) * parity_len
                    buf[missing_seq] = bytes(parity[:last_chunk_len])
                else:
                    buf[missing_seq] = bytes(parity)
                chunks_received += 1
                print(f"[RX FEC] {sender_id}: msgid={msgid} recovered missing seq={missing_seq}")

        if chunks_received != total_chunks:
            print(f"[RX ERROR] {sender_id}: msgid={msgid} expected {total_chunks}, got {chunks_received}. Dropping.")
            _rx_buffers.pop(msg_key, None)
            _rx_timestamps.pop(msg_key, None)
            _rx_parity.pop(msg_key, None)
            return None
        
        # Reassemble chunks in order (seq starts at 1, not 0)
        reassembled = b''
        for i in range(1, total_chunks + 1):
            reassembled += buf[i]
        
        reassembled = reassembled[:orig_len]
        
        print(f"[RX COMPLETE] {sender_id}: msgid={msgid} reassembled {len(reassembled)} bytes")
        
        _rx_buffers.pop(msg_key, None)
        _rx_timestamps.pop(msg_key, None)
        _rx_parity.pop(msg_key, None)
        
        # Return the complete packet
        return (sender_id, reassembled)
    
    else:
        # Data chunk
        buf = _rx_buffers[msg_key]
        buf[seq] = chunk
        print(f"[RX CHUNK] {sender_id}: msgid={msgid} seq={seq} chunk_len={len(chunk)}")
        return None

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

    tun_file, ifname, ip = create_tun_for_node(NODE_ID)
    print(ifname, ip)

    try:
        
        if NODE_ID == 1: 
            tx_radio = setup_radios(MODULE0, FREQUENCY0, NODE_ID, NETWORK_ID, 16, 15, 0, 0) 
            rx_radio = setup_radios(MODULE1, FREQUENCY1, NODE_ID, NETWORK_ID, 18, 22, 0, 1)
        if NODE_ID == 2:
            rx_radio = setup_radios(MODULE0, FREQUENCY0, NODE_ID, NETWORK_ID, 16, 15, 0, 0) 
            tx_radio = setup_radios(MODULE1, FREQUENCY1, NODE_ID, NETWORK_ID, 18, 22, 0, 1)

        while True:
            # Use select() to wait up to 1 ms for TUN data before checking the RX radio.
            # This avoids busy-polling and replaces the old time.sleep(TOSLEEP) idle loop.
            #
            # Throughput math (for reference):
            #   RFM69 at 250 kbps: 61-byte max payload => ~3 ms air-time per frame.
            #   4-byte fragmentation header => 57 bytes of user data per frame.
            #   MTU=120 bytes => ceil(120/57)=3 data frames + 1 END = 4 radio TXs per IP packet.
            #   TOSLEEP=0.005 s per frame => ~200 frames/s => ~11 kB/s (~88 kbps effective).
            #   Old TOSLEEP=0.064 gave only ~860 B/s (~6.8 kbps) — a 13× slowdown.
            r, _, _ = select.select([tun_file], [], [], 0.001)
            if r:
                pkt = read_tun_nonblocking(tun_file)
                if pkt is not None:
                    send_packet(pkt, tx_radio, OTHERNODE, chunk_size=57, rx_radio=rx_radio)

            # Non-blocking receive (packets from RX - write them to TUN)
            result = receive_packet_reassemble(rx_radio)
            if result is not None:
                sender_id, reassembled_pkt = result
                try:
                    os.write(tun_file.fileno(), reassembled_pkt)
                    print(f"[TUN WRITE] Wrote {len(reassembled_pkt)} bytes from {sender_id}")
                except OSError as e:
                    print(f"[TUN ERROR] Failed to write: {e}")

    except:
        print("Shutting down RFM69 modules")
        tx_radio.shutdown()
        rx_radio.shutdown()

if __name__ == "__main__":
    main()
