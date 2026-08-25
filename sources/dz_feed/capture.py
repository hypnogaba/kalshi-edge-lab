"""DoubleZero Top-of-Book & Trades multicast subscriber (server-run).

Runs on the DZ-connected server holding an access pass for the target
multicast group (e.g. the `doublezero1` interface on a DZ tradebot host).
DoubleZero's client kernel-decapsulates the GRE tunnel used for last-mile
delivery, so the application sees plain UDP multicast on that interface --
this module does a normal `IP_ADD_MEMBERSHIP` join, no GRE handling here.

Defaults are Port Set A (Top-of-Book & Trades) on group 233.84.178.15:
  mktdata (Quote/Trade/Heartbeat/EndOfSession):  port 9601
  refdata (InstrumentDefinition/ManifestSummary): port 9602

A subscriber bootstrapping from a cold start MUST bind both ports so it can
resolve InstrumentDefinition alongside live Quote/Trade traffic. Raw frames
(t_arrival_ns, payload) are appended via common.storage.FrameWriter; decoding
happens later/offline via sources.dz_feed.decoder.

Run with --selftest to verify the receive -> store -> decode path end to end
WITHOUT a real feed: it constructs one valid v3 frame, sends it to an
ephemeral loopback UDP socket, and confirms it is received, written, and
decodes to at least one Event.
"""
import argparse
import logging
import os
import select
import socket
import struct
import sys
import tempfile
import time
from socket import inet_aton

from common.clock import now_ns
from common.storage import FrameWriter, read_frames
from sources.dz_feed.decoder import DzDecoder

DEFAULT_GROUP = "233.84.178.15"
DEFAULT_MKTDATA_PORT = 9601
DEFAULT_REFDATA_PORT = 9602

_log = logging.getLogger(__name__)

_RECV_BUFSIZE = 65535  # >> the feed's 1,232B max frame size.


def _join_multicast_socket(group: str, port: int, iface_ip: str | None) -> socket.socket:
    """Open + bind a UDP socket and join `group` on `port` for multicast receive."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", port))
    if iface_ip:
        mreq = struct.pack("4s4s", inet_aton(group), inet_aton(iface_ip))
    else:
        mreq = struct.pack("4sL", inet_aton(group), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.setblocking(False)
    return sock


# --- AF_PACKET link-layer capture --------------------------------------------
# On DoubleZero's tunnel interface (doublezero1) a normal IP_ADD_MEMBERSHIP UDP
# socket receives ZERO datagrams even though the group is joined, the MULTICAST
# flag is set and rp_filter=0 -- the decapsulated multicast never reaches the IP
# socket layer. tcpdump (AF_PACKET) sees the full feed, so we tap the interface
# the same way and parse IP/UDP ourselves, keeping only datagrams addressed to
# `group` on the mktdata/refdata ports. Verified on mainnet-beta: UDP socket 0
# pkts vs AF_PACKET ~3.4k pkts / 5 s on 233.84.178.3:31000.
_ETH_P_IP = 0x0800
_IPPROTO_UDP = 17


def _capture_afpacket(group: str, ports: set[int], link_ifname: str, out_path: str,
                      duration_s: float | None) -> int:
    """Receive off `link_ifname` via AF_PACKET, keep UDP datagrams to `group` on
    `ports`, stamp each on arrival and store the UDP payload (the DZ frame)."""
    group_bytes = inet_aton(group)
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(_ETH_P_IP))
    sock.bind((link_ifname, 0))
    sock.setblocking(False)
    frame_count = 0
    deadline = time.monotonic() + duration_s if duration_s is not None else None
    with FrameWriter(out_path) as writer:
        try:
            while deadline is None or time.monotonic() < deadline:
                select_timeout = 1.0 if deadline is None else max(0.0, deadline - time.monotonic())
                readable, _writable, _errored = select.select([sock], [], [], select_timeout)
                if not readable:
                    continue
                try:
                    data = sock.recv(_RECV_BUFSIZE)
                except OSError:
                    continue
                t_arrival_ns = now_ns()
                # AF_PACKET/SOCK_DGRAM strips the link header: `data` starts at
                # the IPv4 header. Filter to UDP -> our group -> our ports.
                if len(data) < 20 or data[9] != _IPPROTO_UDP:
                    continue
                if data[16:20] != group_bytes:  # destination IP
                    continue
                ihl = (data[0] & 0x0F) * 4
                if len(data) < ihl + 8:
                    continue
                dport = (data[ihl + 2] << 8) | data[ihl + 3]
                if dport not in ports:
                    continue
                writer.write(t_arrival_ns, data[ihl + 8:])  # UDP payload = DZ frame
                frame_count += 1
        finally:
            sock.close()
    return frame_count


def capture(group: str, mktdata_port: int, refdata_port: int, iface_ip: str | None,
            out_path: str, duration_s: float | None = None,
            link_iface: str | None = None) -> int:
    """Capture raw DZ frames, stamping each on arrival, until `duration_s`
    elapses (None runs until interrupted). Returns the datagram count.

    If `link_iface` (an interface NAME, e.g. "doublezero1") is given, capture via
    AF_PACKET -- required on the DZ tunnel, where a UDP multicast socket gets
    nothing. Otherwise join `group` on both ports as a normal UDP multicast
    receiver (`iface_ip` is the local interface IP, or None for INADDR_ANY).
    """
    if link_iface:
        return _capture_afpacket(group, {mktdata_port, refdata_port}, link_iface,
                                 out_path, duration_s)
    mktdata_sock = _join_multicast_socket(group, mktdata_port, iface_ip)
    refdata_sock = _join_multicast_socket(group, refdata_port, iface_ip)
    sockets = [mktdata_sock, refdata_sock]
    frame_count = 0
    deadline = time.monotonic() + duration_s if duration_s is not None else None

    with FrameWriter(out_path) as writer:
        try:
            while deadline is None or time.monotonic() < deadline:
                if deadline is None:
                    select_timeout = 1.0
                else:
                    select_timeout = max(0.0, deadline - time.monotonic())
                readable, _writable, _errored = select.select(sockets, [], [], select_timeout)
                for sock in readable:
                    try:
                        payload, _addr = sock.recvfrom(_RECV_BUFSIZE)
                    except OSError:
                        continue
                    writer.write(now_ns(), payload)
                    frame_count += 1
        finally:
            for sock in sockets:
                sock.close()
    return frame_count


def _build_selftest_frame() -> bytes:
    """One valid v3 frame (InstrumentDefinition + Quote) for --selftest."""

    def msg_header(msg_type: int, length: int, flags: int = 0) -> bytes:
        return struct.pack("<BBH", msg_type, length, flags)

    instrument_def = msg_header(0x02, 130) + struct.pack(
        "<IH64s8s8sBbbBqQQQBBH",
        1, 1, b"SELFTEST", b"", b"", 0, -2, -2, 0, 0, 0, 0, 0, 0, 0, 0,
    )
    quote = msg_header(0x03, 60) + struct.pack(
        "<IHBBQqQqQHH4x",
        1, 1, 0, 0, 0, 1000000, 100, 1000500, 100, 0, 0,
    )
    body = instrument_def + quote
    frame_header = struct.pack("<HBBQQBBH", 0x445A, 3, 1, 1, 0, 2, 0, 24 + len(body))
    return frame_header + body


def _run_selftest() -> bool:
    """Loopback selftest: send one constructed v3 frame to an ephemeral UDP
    socket, confirm it is received, written via FrameWriter, and decodes to
    at least one Event. Proves the receive -> store -> decode path without
    a real multicast feed."""
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    addr = receiver.getsockname()

    frame = _build_selftest_frame()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.sendto(frame, addr)
    sender.close()

    receiver.settimeout(2.0)
    try:
        payload, _from = receiver.recvfrom(_RECV_BUFSIZE)
    except TimeoutError:
        receiver.close()
        print("SELFTEST FAILED: no datagram received on loopback socket")
        return False
    receiver.close()

    t_arrival_ns = now_ns()
    fd, tmp_path = tempfile.mkstemp(suffix=".bin")
    os.close(fd)
    try:
        with FrameWriter(tmp_path) as writer:
            writer.write(t_arrival_ns, payload)
        stored = list(read_frames(tmp_path))
    finally:
        os.unlink(tmp_path)

    if len(stored) != 1:
        print(f"SELFTEST FAILED: expected 1 stored frame, got {len(stored)}")
        return False

    events = DzDecoder().decode(stored[0][1], stored[0][0])
    if len(events) < 1:
        print("SELFTEST FAILED: decode produced 0 events")
        return False

    print(
        f"SELFTEST OK: sent {len(frame)}B frame -> received {len(payload)}B datagram "
        f"-> stored 1 frame -> decoded {len(events)} event(s) "
        f"({[e.kind.value for e in events]})"
    )
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--group", default=DEFAULT_GROUP, help="Multicast group address")
    ap.add_argument("--mktdata-port", type=int, default=DEFAULT_MKTDATA_PORT)
    ap.add_argument("--refdata-port", type=int, default=DEFAULT_REFDATA_PORT)
    ap.add_argument("--iface", default=None,
                     help="Local interface IP to join on (e.g. the doublezero1 address); "
                          "omit to join on INADDR_ANY")
    ap.add_argument("--link", default=None,
                     help="Interface NAME (e.g. doublezero1) to capture via AF_PACKET; "
                          "required on the DZ tunnel, where a UDP multicast socket gets nothing")
    ap.add_argument("--minutes", type=float, default=None,
                     help="Stop after this many minutes; omit to run until interrupted")
    ap.add_argument("--out", default=None, help="Output frame-log path (required unless --selftest)")
    ap.add_argument("--selftest", action="store_true",
                     help="Run the loopback receive/store/decode selftest and exit")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if _run_selftest() else 1)

    if not args.out:
        ap.error("--out is required unless --selftest")

    duration_s = args.minutes * 60 if args.minutes else None
    frame_count = capture(args.group, args.mktdata_port, args.refdata_port, args.iface,
                          args.out, duration_s, link_iface=args.link)
    _log.info("captured %d frames -> %s", frame_count, args.out)


if __name__ == "__main__":
    main()
