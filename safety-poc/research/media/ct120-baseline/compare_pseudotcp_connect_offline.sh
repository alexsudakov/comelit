#!/usr/bin/env bash
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PCAP="${1:-/root/comelit-artifacts/self_activation.pcap}"
LOCAL_IP="${2:-10.215.173.1}"
BUILD=/root/comelit-pseudotcp-connect-compare
SRC="$BUILD/connect_probe.c"
BIN="$BUILD/connect_probe"
WIRE="$BUILD/local-connect.bin"
CAPTURE_JSON="$BUILD/capture.json"
LOCAL_JSON="$BUILD/local.json"

for cmd in python3 gcc pkg-config; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "MISSING_COMMAND=$cmd"
        exit 10
    }
done

[[ -f "$PCAP" ]] || { echo "PCAP_MISSING=$PCAP"; exit 11; }

rm -rf "$BUILD"
mkdir -m 700 "$BUILD"

cat >"$SRC" <<'C'
#include <nice/pseudotcp.h>
#include <glib.h>
#include <stdio.h>

static const char *out_path = NULL;

static void opened(PseudoTcpSocket *tcp, gpointer data) {(void)tcp;(void)data;}
static void readable(PseudoTcpSocket *tcp, gpointer data) {(void)tcp;(void)data;}
static void writable(PseudoTcpSocket *tcp, gpointer data) {(void)tcp;(void)data;}
static void closed(PseudoTcpSocket *tcp, guint32 error, gpointer data) {(void)tcp;(void)error;(void)data;}

static PseudoTcpWriteResult write_packet(
    PseudoTcpSocket *tcp,
    const gchar *buffer,
    guint32 len,
    gpointer data)
{
    (void)tcp;
    (void)data;
    FILE *f = fopen(out_path, "wb");
    if (!f)
        return WR_FAIL;
    size_t n = fwrite(buffer, 1, len, f);
    fclose(f);
    return n == len ? WR_SUCCESS : WR_FAIL;
}

int main(int argc, char **argv)
{
    if (argc != 2)
        return 2;
    out_path = argv[1];

    PseudoTcpCallbacks cb = {
        .user_data = NULL,
        .PseudoTcpOpened = opened,
        .PseudoTcpReadable = readable,
        .PseudoTcpWritable = writable,
        .PseudoTcpClosed = closed,
        .WritePacket = write_packet,
    };

    PseudoTcpSocket *tcp = pseudo_tcp_socket_new(0, &cb);
    if (!tcp)
        return 3;

    pseudo_tcp_socket_notify_mtu(tcp, 1320);
    gboolean ok = pseudo_tcp_socket_connect(tcp);
    g_object_unref(tcp);
    return ok ? 0 : 4;
}
C

CFLAGS="$(pkg-config --cflags nice glib-2.0 gobject-2.0)"
LIBS="$(pkg-config --libs nice glib-2.0 gobject-2.0)"
gcc -std=c11 -O2 -Wall -Wextra $CFLAGS "$SRC" -o "$BIN" $LIBS
"$BIN" "$WIRE"

echo '=== CT120 LIBNICE ==='
pkg-config --modversion nice | sed 's/^/LIBNICE_VERSION=/'

python3 - "$PCAP" "$LOCAL_IP" "$CAPTURE_JSON" <<'PY'
from __future__ import annotations
import ipaddress, json, struct, sys
from pathlib import Path

pcap = Path(sys.argv[1])
local_ip = ipaddress.ip_address(sys.argv[2]).packed
out = Path(sys.argv[3])
data = pcap.read_bytes()

if len(data) < 24:
    raise SystemExit('PCAP_SHORT')
magic = data[:4]
if magic == b'\xd4\xc3\xb2\xa1':
    endian = '<'
elif magic == b'\xa1\xb2\xc3\xd4':
    endian = '>'
elif magic == b'\x4d\x3c\xb2\xa1':
    endian = '<'
elif magic == b'\xa1\xb2\x3c\x4d':
    endian = '>'
else:
    raise SystemExit('PCAP_FORMAT_UNSUPPORTED')
linktype = struct.unpack(endian + 'I', data[20:24])[0]
if linktype != 101:
    raise SystemExit(f'LINKTYPE_UNSUPPORTED={linktype}')


def udp_payload(pkt: bytes):
    if len(pkt) < 28 or (pkt[0] >> 4) != 4:
        return None
    ihl = (pkt[0] & 0x0f) * 4
    if ihl < 20 or len(pkt) < ihl + 8 or pkt[9] != 17:
        return None
    total_len = struct.unpack('!H', pkt[2:4])[0]
    if total_len == 0 or total_len > len(pkt):
        total_len = len(pkt)
    src = pkt[12:16]
    dst = pkt[16:20]
    udp = pkt[ihl:total_len]
    if len(udp) < 8:
        return None
    ulen = struct.unpack('!H', udp[4:6])[0]
    if ulen < 8:
        return None
    end = min(len(udp), ulen)
    return src, dst, udp[8:end]


def strict_connect(payload: bytes):
    if len(payload) < 25:
        return None
    conv, seq, ack = struct.unpack('!III', payload[:12])
    flags = payload[13]
    body = payload[24:]

    # Capture-proven PseudoTCP contract for the client-side initial CONNECT:
    # conversation 0, CTL flag only, seq=ack=0, first data byte CTL_CONNECT=0.
    # This intentionally rejects unrelated ViP/media UDP datagrams which may
    # coincidentally have bit 0x02 set in byte 13.
    if conv != 0 or flags != 2 or seq != 0 or ack != 0:
        return None
    if not body or body[0] != 0:
        return None

    return {
        'wire_len': len(payload),
        'data_len': len(body),
        'conversation': conv,
        'flags': flags,
        'seq_zero': True,
        'ack_zero': True,
        'data_hex': body.hex(),
        'control_byte': body[0],
        'window': struct.unpack('!H', payload[14:16])[0],
    }


pos = 24
found = None
while pos + 16 <= len(data):
    _ts_sec, _ts_frac, incl_len, _orig_len = struct.unpack(endian + 'IIII', data[pos:pos+16])
    pos += 16
    if pos + incl_len > len(data):
        break
    pkt = data[pos:pos+incl_len]
    pos += incl_len
    parsed = udp_payload(pkt)
    if not parsed:
        continue
    src, _dst, payload = parsed
    if src != local_ip:
        continue
    p = strict_connect(payload)
    if p is not None:
        found = p
        break

if found is None:
    raise SystemExit('CAPTURE_CONNECT_NOT_FOUND')
out.write_text(json.dumps(found, sort_keys=True), encoding='utf-8')
print('CAPTURE_CONNECT_EXTRACT=PASS')
print('CAPTURE_MATCH_FILTER=conv0_flags2_seq0_ack0_ctl_connect0')
PY

python3 - "$WIRE" "$LOCAL_JSON" <<'PY'
from __future__ import annotations
import json, struct, sys
from pathlib import Path
p = Path(sys.argv[1]).read_bytes()
if len(p) < 24:
    raise SystemExit('LOCAL_CONNECT_SHORT')
conv, seq, ack = struct.unpack('!III', p[:12])
flags = p[13]
body = p[24:]
obj = {
    'wire_len': len(p),
    'data_len': len(body),
    'conversation': conv,
    'flags': flags,
    'seq_zero': seq == 0,
    'ack_zero': ack == 0,
    'data_hex': body.hex(),
    'control_byte': body[0] if body else None,
    'window': struct.unpack('!H', p[14:16])[0],
}
Path(sys.argv[2]).write_text(json.dumps(obj, sort_keys=True), encoding='utf-8')
print('LOCAL_CONNECT_GENERATE=PASS')
PY

python3 - "$CAPTURE_JSON" "$LOCAL_JSON" <<'PY'
from __future__ import annotations
import json, sys
from pathlib import Path
cap = json.loads(Path(sys.argv[1]).read_text())
loc = json.loads(Path(sys.argv[2]).read_text())

print('=== SUCCESSFUL CAPTURE CONNECT ===')
for k in ('wire_len','data_len','conversation','flags','seq_zero','ack_zero','window','control_byte','data_hex'):
    print(f'CAPTURE_{k.upper()}={cap[k]}')

print('\n=== CT120 LIBNICE CONNECT ===')
for k in ('wire_len','data_len','conversation','flags','seq_zero','ack_zero','window','control_byte','data_hex'):
    print(f'LOCAL_{k.upper()}={loc[k]}')

structural = ('wire_len','data_len','conversation','flags','seq_zero','ack_zero','control_byte','data_hex')
mismatches = [k for k in structural if cap[k] != loc[k]]
print('\n=== COMPARISON ===')
print('CONNECT_STRUCTURAL_MATCH=' + ('true' if not mismatches else 'false'))
print('CONNECT_MISMATCH_FIELDS=' + (','.join(mismatches) if mismatches else 'NONE'))
print('WINDOW_MATCH=' + str(cap['window'] == loc['window']).lower())
print('NETWORK_IO_PERFORMED=false')
print('DOOR_ACTION_SENT=false')
print('MEDIA_ACTION_SENT=false')
if mismatches:
    raise SystemExit(20)
print('PSEUDOTCP_CONNECT_COMPARE=PASS')
PY
