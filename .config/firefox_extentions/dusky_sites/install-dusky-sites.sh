#!/usr/bin/env bash
# install-dusky-sites.sh — install the native host + manifest, verify toolchain, build the xpi, smoke-test the wire.
# usage: ./install-dusky-sites.sh [repo-root]   (repo-root contains extension/ and dusky_sites_host.py)
set -euo pipefail

SRC="$(realpath "${1:-$PWD}")"
HOST_DST="$HOME/.local/share/dusky-sites/dusky_sites_host.py"
NM_DIR="$HOME/.mozilla/native-messaging-hosts"
EXT_ID="dusky_sites@dusky.com"

echo "== toolchain"
python3 -c 'import sys; assert sys.version_info >= (3, 14, 7), sys.version; print("python", sys.version.split()[0])'
firefox --version | tee /dev/stderr | grep -Eq 'Firefox (15[6-9]|1[6-9][0-9])' || { echo "Firefox >= 156 required" >&2; exit 1; }
if command -v node >/dev/null; then
  node --check "$SRC/extension/background.js"
  node --check "$SRC/extension/content.js"
  node --check "$SRC/extension/defaults.js"
  echo "js syntax ok"
else
  echo "node not found: skipping --check (pacman -S nodejs)"
fi
python3 -m json.tool "$SRC/extension/manifest.json" >/dev/null && echo "manifest json ok"

echo "== host"
install -Dm755 "$SRC/dusky_sites_host.py" "$HOST_DST"
python3 -m py_compile "$HOST_DST" && echo "py_compile ok"
install -d "$NM_DIR"
cat > "$NM_DIR/dusky_sites.json" <<EOF
{
  "name": "dusky_sites",
  "description": "Dusky Sites Native Messaging Host",
  "path": "$HOST_DST",
  "type": "stdio",
  "allowed_extensions": ["$EXT_ID"]
}
EOF
echo "native manifest → $NM_DIR/dusky_sites.json"
install -d "$HOME/.config/dusky/settings/dusky_sites" "$HOME/.config/dusky_sites"

echo "== wire smoke test (HELLO → HELLO_ACK, FETCH_NOW → MATUGEN_UPDATE, delta path, EOF → exit 0)"
python3 - "$HOST_DST" "$NM_DIR/dusky_sites.json" "$EXT_ID" <<'PY'
import json, struct, subprocess, sys, time
host, manifest, ext = sys.argv[1:4]
p = subprocess.Popen([host, manifest, ext], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
def send(m):
    b = json.dumps(m).encode(); p.stdin.write(struct.pack('=I', len(b)) + b); p.stdin.flush()
def recv(want):
    while True:
        h = p.stdout.read(4); assert len(h) == 4, 'host closed early'
        m = json.loads(p.stdout.read(struct.unpack('=I', h)[0]))
        if m.get('type') == want:
            return m
send({'type': 'HELLO', 'wire': 3, 'extension': ext, 'known': {}})
ack = recv('HELLO_ACK'); assert ack['wire'] >= 3, ack
t0 = time.perf_counter(); send({'type': 'FETCH_NOW', 'known': {}}); m = recv('MATUGEN_UPDATE'); dt = (time.perf_counter() - t0) * 1000
d = m['data']; print(f"MATUGEN_UPDATE in {dt:.1f} ms: {len(d['colors'])} colours, {len(d.get('websites', {}))} site keys, status={d['status']}")
assert 'websites' in d, 'first frame must carry the rule map'
send({'type': 'FETCH_NOW', 'known': {'websitesRev': d['websitesRev']}}); m2 = recv('MATUGEN_UPDATE')
assert 'websites' not in m2['data'], 'delta path failed: websites re-sent although known'
print("delta ok: second FETCH_NOW omitted websites")
send({'type': 'PING', 'at': 1}); assert recv('PONG')['at'] == 1
p.stdin.close(); print("exit", p.wait(timeout=5))
PY

echo "== xpi"
( cd "$SRC/extension" && rm -f ../dusky_sites.xpi && zip -qr -X ../dusky_sites.xpi manifest.json background.js content.js defaults.js icons )
echo "built $SRC/dusky_sites.xpi"
echo "load via about:debugging#/runtime/this-firefox → Load Temporary Add-on → $SRC/extension/manifest.json"
