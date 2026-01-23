#!/usr/bin/env python3
#
# TwinRF69_test_tun_bridge.py
#
# Simplified TUN bridge based on TwinRF69_test.py style.
# TX/RX radio selection is fixed by NODE_ID:
#   - If NODE_ID == 1: TX = radio1 (915MHz), RX = radio0 (433MHz)
#   - If NODE_ID == 2: TX = radio0 (433MHz), RX = radio1 (915MHz)
#
# This update improves the RX loop: it arms the RX radio once, polls receiveDone()
# and prints debug information (PAYLOADLEN, SENDERID, RSSI, DATA preview) so you can
# see what the driver reports. It re-arms RX after processing each packet.
#
# Keep this file in Code/ and run from that directory so it imports RFM69.py
#

import os
import time
import struct
import tempfile
import binascii
import socket
import sys
import RPi.GPIO as GPIO

import RFM69
from RFM69registers import *

# ---- User-configurable constants (match TwinRF69_test.py style) ----
REGION = 1            # 1 => 433/915; 2 => 433/868
NODE_ID = 1           # set to 1 or 2 to pick TX/RX roles automatically
OTHERNODE = 2
NETWORK_ID = 0
TOSLEEP = 0.01
TIMEOUT = 1

packet_size = 62      # used by file send functions (chunk size)
# --------------------------------------------------------------------

# Simple protocol:
# Each radio payload contains a 4-byte header followed by chunk:
#   MSGID (uint16, big-endian), SEQ (uint16, big-endian)
# - SEQ values 0..N-1 are data chunks
# - SEQ == 0xFFFF is an "END" marker; its payload is two uint16 BE: total_chunks, orig_len
#
# Receiver collects chunks per MSGID until it sees END, then reassembles and writes to tun.

NEXT_MSG_ID = 1

def next_msg_id():
    global NEXT_MSG_ID
    v = NEXT_MSG_ID
    NEXT_MSG_ID = (NEXT_MSG_ID + 1) & 0xFFFF
    if NEXT_MSG_ID == 0:
        NEXT_MSG_ID = 1
    return v

def open_tun(ifname='tun0'):
    """
    Create /dev/net/tun device and return fd.
    Minimal wrapper matching the repo's style. Must run as root.
    """
    import fcntl
    TUNSETIFF = 0x400454ca
    IFF_TUN   = 0x0001
    IFF_NO_PI = 0x1000

    tun_fd = os.open("/dev/net/tun", os.O_RDWR)
    ifr = struct.pack('16sH', ifname.encode('utf-8'), IFF_TUN | IFF_NO_PI)
    fcntl.ioctl(tun_fd, TUNSETIFF, ifr)
    return tun_fd

def divide_bytes_into_chunks(data_bytes, chunk_size):
    chunks = []
    i = 0
    while i < len(data_bytes):
        chunks.append(data_bytes[i:i+chunk_size])
        i += chunk_size
    if len(chunks) == 0:
        chunks.append(b'')
    return chunks

def send_binary_over_radios(data_bytes, chunk_size, radio_tx):
    """
    Send binary data by splitting into chunks and transmitting each chunk.
    Uses header [MSGID:2][SEQ:2] then payload.
    After all data chunks are sent, send an END packet [MSGID][0xFFFF] + [total:uint16][orig_len:uint16]
    radio_tx.send(toAddress, buff, requestACK=False) expects list-of-int or bytes-like.
    """
    msgid = next_msg_id()
    chunks = divide_bytes_into_chunks(data_bytes, chunk_size)
    total = len(chunks)
    try:
        for seq, c in enumerate(chunks):
            hdr = struct.pack('!H H', msgid, seq)
            frame = hdr + c
            # radio.send accepts list-of-int in this repo; pass list(frame)
            radio_tx.send(OTHERNODE, list(frame))
            time.sleep(0.06)
        # send END marker with total and original length
        hdr = struct.pack('!H H', msgid, 0xFFFF)
        meta = struct.pack('!H H', total, len(data_bytes) if len(data_bytes) < 0xFFFF else 0xFFFF)
        radio_tx.send(OTHERNODE, list(hdr + meta))
        time.sleep(0.06)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print("send_binary_over_radios: exception while sending:", e)

def _preview_bytes(b, length=32):
    try:
        return ' '.join(f"{x:02x}" for x in b[:length])
    except Exception:
        try:
            return binascii.hexlify(b[:length]).decode('ascii')
        except Exception:
            return str(b)[:length]

def receive_loop_write_to_file(output_path, radio_rx, radio_tx, tun_fd=None, chunk_timeout=TIMEOUT):
    """
    Improved receiver loop. Arms radio_rx once and continuously polls receiveDone().
    Prints debug info so you can see what's arriving from the driver.
    Writes reassembled messages to file and/or tun_fd.
    """
    buffers = {}

    # Arm RX once
    try:
        radio_rx.receiveBegin()
    except Exception:
        pass

    try:
        while True:
            # Poll for a received packet
            try:
                if radio_rx.receiveDone():
                    # debug info: PAYLOADLEN, SENDERID, RSSI
                    paylen = getattr(radio_rx, 'PAYLOADLEN', None)
                    sender = getattr(radio_rx, 'SENDERID', None)
                    rssi = getattr(radio_rx, 'RSSI', None)
                    data_raw = getattr(radio_rx, 'DATA', None)
                    if data_raw is None:
                        data = b''
                    else:
                        # repo stores DATA as list of ints; convert safely
                        if isinstance(data_raw, (list, tuple)):
                            data = bytes(data_raw)
                        elif isinstance(data_raw, bytes):
                            data = data_raw
                        elif isinstance(data_raw, str):
                            data = data_raw.encode('latin1')
                        else:
                            # fallback: try bytes()
                            try:
                                data = bytes(data_raw)
                            except Exception:
                                data = b''

                    print(f"[RX DEBUG] PAYLOADLEN={paylen} SENDER={sender} RSSI={rssi} LEN={len(data)} preview={_preview_bytes(data, 32)}")

                    # parse our simple 4-byte header
                    if len(data) >= 4:
                        try:
                            msgid, seq = struct.unpack('!H H', data[:4])
                        except struct.error:
                            print("[RX DEBUG] header unpack failed")
                            msgid = None
                            seq = None
                        payload = data[4:]
                        if msgid is not None:
                            if msgid not in buffers:
                                buffers[msgid] = {"total": None, "chunks": {}, "first": time.time()}
                            buf = buffers[msgid]
                            if seq == 0xFFFF:
                                # END marker with total and orig_len
                                if len(payload) >= 4:
                                    total, orig_len = struct.unpack('!H H', payload[:4])
                                    buf["total"] = total
                                else:
                                    buf["total"] = buf.get("total", 0)
                            else:
                                buf["chunks"][seq] = payload

                            # if complete, reassemble
                            if buf["total"] is not None and len(buf["chunks"]) >= buf["total"]:
                                parts = [buf["chunks"].get(i, b'') for i in range(buf["total"])]
                                out = b"".join(parts)
                                if output_path:
                                    try:
                                        with open(output_path, 'wb') as f:
                                            f.write(out)
                                        print("Wrote received message to", output_path, "len", len(out))
                                    except Exception as e:
                                        print("Failed to write to file:", e)
                                if tun_fd:
                                    try:
                                        os.write(tun_fd, out)
                                        print("Wrote received message into TUN (len {})".format(len(out)))
                                    except Exception as e:
                                        print("Failed writing to TUN:", e)
                                del buffers[msgid]
                    else:
                        print("[RX DEBUG] received packet too short to parse header, ignoring")

                    # Re-arm receiver
                    try:
                        radio_rx.receiveBegin()
                    except Exception:
                        pass
                else:
                    # no packet, idle briefly
                    time.sleep(0.005)
            except Exception as e:
                print("receive_loop: exception while polling RX:", e)
                time.sleep(0.05)
    except KeyboardInterrupt:
        print("receive_loop_write_to_file: interrupted by user, exiting.")
    finally:
        try:
            radio_rx.shutdown()
        except Exception:
            pass

def listen_tun_and_send(radio_tx, chunk_size, tun_name='tun0', stop_event=None):
    """
    Listen on the TUN device `tun_name`, for each IP packet read:
      - call send_binary_over_radios(packet, chunk_size, radio_tx)
    """
    try:
        tun_fd = open_tun(tun_name)
    except Exception as e:
        print("listen_tun_and_send: failed to open tun:", e)
        return

    print("listen_tun_and_send: listening on", tun_name)
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            pkt = os.read(tun_fd, 4096)
            if not pkt:
                time.sleep(0.01)
                continue
            print("TUN-> read packet", len(pkt), "bytes")
            send_binary_over_radios(pkt, chunk_size, radio_tx)
    except KeyboardInterrupt:
        print("listen_tun_and_send: interrupted by user")
    finally:
        try:
            os.close(tun_fd)
        except Exception:
            pass

# --- minimal radio setup function copied / adapted from TwinRF69_test.py to keep conventions ---
def setup_radios(MODULE, FREQUENCY, NODE_ID, NETWORK_ID, INT_PIN, RST_PIN, SPI_BUS, SPI_DEV, isHighPower=True):
    radio = RFM69.RFM69(freqBand=MODULE,
                        nodeID=NODE_ID,
                        networkID=NETWORK_ID,
                        isRFM69HW=isHighPower,
                        intPin=INT_PIN,
                        rstPin=RST_PIN,
                        spiBus=SPI_BUS,
                        spiDevice=SPI_DEV)
    print("Class initialized")
    radio.rcCalibration()
    radio.setHighPower(isHighPower)
    radio.setPowerLevel(31)
    radio.setFrequency(FREQUENCY)
    radio.writeReg(REG_BITRATEMSB, RF_BITRATEMSB_250000)
    radio.writeReg(REG_BITRATELSB, RF_BITRATELSB_250000)
    radio.writeReg(REG_FDEVMSB, RF_FDEVMSB_50000)
    radio.writeReg(REG_FDEVLSB, RF_FDEVLSB_50000)
    return radio

def main():
    global REGION, NODE_ID, OTHERNODE, NETWORK_ID, packet_size

    if (REGION == 1):
        print("Entering 433MHz and 915MHz mode")
        MODULE1 = RF69_915MHZ
        FREQUENCY1 = 915000000
    elif (REGION == 2):
        print("Entering 433MHz and 868MHz mode")
        MODULE1 = RF69_868MHZ
        FREQUENCY1 = 868000000
    else:
        raise Exception("Region not set")

    MODULE0 = RF69_433MHZ
    FREQUENCY0 = 433000000

    OUTPUT_FILE = 'received_file.bin'
    file_path = 'logo.png'
    chunk_size = 60

    # Setup GPIO like original
    GPIO.setmode(GPIO.BOARD)
    led = 5
    GPIO.setup(led, GPIO.OUT)
    GPIO.output(led, GPIO.LOW)

    try:
        # initialize radios exactly like original script
        radio0 = setup_radios(MODULE0, FREQUENCY0, NODE_ID, NETWORK_ID, 16, 15, 0, 0)
        radio1 = setup_radios(MODULE1, FREQUENCY1, NODE_ID, NETWORK_ID, 18, 22, 0, 1)

        # Simple TX/RX selection based on NODE_ID:
        if NODE_ID == 1:
            radio_tx = radio1   # 915 MHz
            radio_rx = radio0   # 433 MHz
        elif NODE_ID == 2:
            radio_tx = radio0   # 433 MHz
            radio_rx = radio1   # 915 MHz
        else:
            radio_tx = radio1
            radio_rx = radio0
        print("Node ID:", NODE_ID, "-> TX is", ("radio1 (915MHz)" if radio_tx is radio1 else "radio0 (433MHz)"),
              " RX is", ("radio0 (433MHz)" if radio_rx is radio0 else "radio1 (915MHz)"))

        while True:
            print("Please choose an option:")
            print("1. Send a file")
            print("2. Receive a file (write to disk)")
            print("3. TUN bridge (read tun -> tx; rx -> tun)")
            print("4. Listen on tun0 (debug raw)")
            response = input("Enter 1-4: ").strip()

            if response == '1':
                if not os.path.exists(file_path):
                    print("File not found:", file_path)
                    continue
                with open(file_path, 'rb') as f:
                    data = f.read()
                print("Sending file", file_path, "size", len(data))
                send_binary_over_radios(data, chunk_size, radio_tx)

            elif response == '2':
                print("Receiving file and writing to", OUTPUT_FILE)
                receive_loop_write_to_file(OUTPUT_FILE, radio_rx, radio_tx, tun_fd=None)

            elif response == '3':
                tunname = input("TUN interface name (default tun0): ").strip() or 'tun0'
                local_ip = input("Local IP/CIDR to assign (e.g. 10.0.0.1/30) or leave blank: ").strip()
                try:
                    tun_fd = open_tun(tunname)
                    print("Opened TUN device", tunname)
                    if local_ip:
                        os.system(f"ip addr add {local_ip} dev {tunname}")
                        os.system(f"ip link set {tunname} up")
                    print("Starting TUN bridge. Ctrl-C to stop.")
                    import threading
                    stop_ev = threading.Event()
                    rx_thread = threading.Thread(target=receive_loop_write_to_file, args=(None, radio_rx, radio_tx, tun_fd), daemon=True)
                    rx_thread.start()
                    try:
                        while True:
                            pkt = os.read(tun_fd, 4096)
                            if not pkt:
                                time.sleep(0.01)
                                continue
                            print("TUN read", len(pkt), "bytes -> sending")
                            send_binary_over_radios(pkt, chunk_size, radio_tx)
                    except KeyboardInterrupt:
                        print("TUN bridge interrupted by user")
                        stop_ev.set()
                        rx_thread.join(timeout=1.0)
                    finally:
                        try:
                            os.close(tun_fd)
                        except Exception:
                            pass
                except PermissionError:
                    print("Need root privileges to open /dev/net/tun")
                except Exception as e:
                    print("Could not start TUN bridge:", e)

            elif response == '4':
                listen_tun0('tun0')

            else:
                print("Invalid input. Please enter 1-4.")

    except Exception as e:
        print("Shutting down RFM69 modules:", e)
        try:
            radio_tx.shutdown()
        except Exception:
            pass
        try:
            radio_rx.shutdown()
        except Exception:
            pass

def listen_tun0(iface='tun0'):
    """
    Small helper that prints incoming packets on tun (mirrors previous helper)
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
            offset = 0
            if len(pkt) >= 14 and pkt[12:14] == b'\x08\x00':
                offset = 14
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
                except struct.error:
                    print(" Received packet but failed to parse IP header; raw len:", len(pkt))
            else:
                preview = binascii.hexlify(pkt[:64]).decode('ascii')
                grouped = ' '.join(preview[i:i+2] for i in range(0, min(len(preview), 128), 2))
                print(f"[{time.strftime('%H:%M:%S')}] Raw pkt len={len(pkt)} preview: {grouped}")
    except KeyboardInterrupt:
        print("\nStopped listening on", iface)
    finally:
        try:
            s.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
