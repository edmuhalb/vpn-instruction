#!/usr/bin/env python3
import subprocess
import json
import re
import base64
from http.server import HTTPServer, BaseHTTPRequestHandler

SERVER_IP   = "194.226.169.15"
SERVER_PORT = "37930"
SUBNET      = "10.8.1"
CONF_PATH   = "/opt/amnezia/awg/awg0.conf"
CONTAINER   = "amnezia-awg2"
API_SECRET  = "11111111"

AWG_PARAMS = {
    "Jc": "4", "Jmin": "10", "Jmax": "50",
    "S1": "147", "S2": "29", "S3": "21", "S4": "6",
    "H1": "1209694282", "H2": "1816253784",
    "H3": "1999736174", "H4": "2099948346"
}

# In-memory log ring buffer
import datetime
_logs = []
def log(level, msg):
    entry = {"t": datetime.datetime.utcnow().isoformat(), "level": level, "msg": msg}
    _logs.append(entry)
    if len(_logs) > 200:
        _logs.pop(0)
    print("[%s] %s: %s" % (entry["t"], level, msg))

def docker_exec(cmd):
    r = subprocess.run(["docker", "exec", CONTAINER] + cmd, capture_output=True, text=True)
    return r.stdout.strip()

def docker_exec_input(cmd, stdin_data):
    r = subprocess.run(["docker", "exec", "-i", CONTAINER] + cmd, input=stdin_data, capture_output=True, text=True)
    return r.stdout.strip()

def get_server_pubkey():
    conf = docker_exec(["cat", CONF_PATH])
    for line in conf.splitlines():
        if line.startswith("PrivateKey"):
            privkey = line.split("=", 1)[1].strip()
            return docker_exec_input(["awg", "pubkey"], privkey)
    return None

def get_next_ip():
    conf = docker_exec(["cat", CONF_PATH])
    used = [int(m.group(1)) for m in (re.search(r'AllowedIPs\s*=\s*10\.8\.1\.(\d+)', l) for l in conf.splitlines()) if m]
    for i in range(2, 255):
        if i not in used:
            return "%s.%d" % (SUBNET, i)
    return None

def get_preshared_key():
    conf = docker_exec(["cat", CONF_PATH])
    for line in conf.splitlines():
        if line.startswith("PresharedKey"):
            return line.split("=", 1)[1].strip()
    return docker_exec(["awg", "genpsk"])

def create_user(name):
    client_privkey = docker_exec(["awg", "genkey"])
    client_pubkey  = docker_exec_input(["awg", "pubkey"], client_privkey)
    preshared_key  = get_preshared_key()
    client_ip      = get_next_ip()
    server_pubkey  = get_server_pubkey()

    if not client_ip:
        return None, None, "Нет свободных IP"
    if not server_pubkey:
        return None, None, "Ошибка получения ключа сервера"

    peer_block = "\n[Peer]\n# %s\nPublicKey = %s\nPresharedKey = %s\nAllowedIPs = %s/32\n" % (
        name, client_pubkey, preshared_key, client_ip)
    subprocess.run(["docker", "exec", "-i", CONTAINER, "sh", "-c",
        "printf '%%s' '%s' >> %s" % (peer_block, CONF_PATH)])
    subprocess.run(["docker", "exec", CONTAINER, "awg", "set", "awg0",
        "peer", client_pubkey, "allowed-ips", "%s/32" % client_ip])

    p = AWG_PARAMS
    client_conf = (
        "[Interface]\nPrivateKey = %s\nAddress = %s/24\nDNS = 1.1.1.1, 8.8.8.8\n"
        "Jc = %s\nJmin = %s\nJmax = %s\nS1 = %s\nS2 = %s\nS3 = %s\nS4 = %s\n"
        "H1 = %s\nH2 = %s\nH3 = %s\nH4 = %s\n\n"
        "[Peer]\nPublicKey = %s\nPresharedKey = %s\nEndpoint = %s:%s\n"
        "AllowedIPs = 0.0.0.0/0\nPersistentKeepalive = 25\n"
    ) % (client_privkey, client_ip,
         p["Jc"], p["Jmin"], p["Jmax"], p["S1"], p["S2"], p["S3"], p["S4"],
         p["H1"], p["H2"], p["H3"], p["H4"],
         server_pubkey, preshared_key, SERVER_IP, SERVER_PORT)

    amnezia_data = {
        "containers": [{"awg": dict(list(p.items()) + [("last_config", client_conf)]), "container": "amnezia-awg"}],
        "defaultContainer": "amnezia-awg",
        "description": "VPN (%s)" % name,
        "dns1": "1.1.1.1", "dns2": "8.8.8.8",
        "hostName": SERVER_IP, "port": SERVER_PORT,
        "splitTunnelSites": [], "splitTunnelType": 0
    }
    vpn_url = "vpn://" + base64.urlsafe_b64encode(json.dumps(amnezia_data).encode()).decode()
    return client_conf, vpn_url, None

def list_users():
    conf = docker_exec(["cat", CONF_PATH])
    users, current = [], {}
    for line in conf.splitlines():
        line = line.strip()
        if line == "[Peer]":
            if current:
                users.append(current)
            current = {}
        elif line.startswith("# "):
            current["name"] = line[2:]
        elif line.startswith("PublicKey"):
            current["pubkey"] = line.split("=", 1)[1].strip()
        elif line.startswith("AllowedIPs"):
            current["ip"] = line.split("=", 1)[1].strip()
    if current:
        users.append(current)
    try:
        awg_show = docker_exec(["awg", "show", "awg0"])
        active = {l.strip().split("peer:")[1].strip() for l in awg_show.splitlines() if l.strip().startswith("peer:")}
        for u in users:
            u["active"] = u.get("pubkey", "") in active
    except Exception:
        pass
    return users

def delete_user(pubkey):
    subprocess.run(["docker", "exec", CONTAINER, "awg", "set", "awg0", "peer", pubkey, "remove"])
    conf = docker_exec(["cat", CONF_PATH])
    lines = conf.splitlines()
    result, i = [], 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "[Peer]":
            block = [line]
            i += 1
            while i < len(lines) and lines[i].strip() != "[Peer]":
                block.append(lines[i])
                i += 1
            if not any(pubkey in l for l in block):
                result.extend(block)
        else:
            result.append(line)
            i += 1
    subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", "cat > %s" % CONF_PATH],
        input="\n".join(result), text=True)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass

    def send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Secret")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def check_secret(self):
        return self.headers.get("X-Secret", "") == API_SECRET

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Secret")
        self.end_headers()

    def do_GET(self):
        if self.path == "/logs":
            if not self.check_secret(): return self.send_json(403, {"error": "Forbidden"})
            return self.send_json(200, {"logs": _logs[-50:]})
        if self.path != "/users": return self.send_json(404, {"error": "Not found"})
        if not self.check_secret(): return self.send_json(403, {"error": "Forbidden"})
        self.send_json(200, {"users": list_users()})

    def do_POST(self):
        if self.path != "/create": return self.send_json(404, {"error": "Not found"})
        if not self.check_secret(): return self.send_json(403, {"error": "Forbidden"})
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        name = body.get("name", "user").strip() or "user"
        conf, vpn_url, err = create_user(name)
        if err:
            self.send_json(200, {"error": err})
        else:
            self.send_json(200, {"config": conf, "url": vpn_url, "name": name})

    def do_DELETE(self):
        if self.path != "/users": return self.send_json(404, {"error": "Not found"})
        if not self.check_secret(): return self.send_json(403, {"error": "Forbidden"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            log("INFO", "DELETE body raw: %s" % raw)
            body = json.loads(raw)
            pubkey = (body.get("pubkey") or "").strip()
            if not pubkey: return self.send_json(400, {"error": "pubkey required"})
            log("INFO", "Deleting pubkey: %s" % pubkey)
            delete_user(pubkey)
            log("INFO", "Deleted OK: %s" % pubkey)
            self.send_json(200, {"ok": True})
        except Exception as e:
            log("ERROR", "DELETE error: %s" % str(e))
            self.send_json(500, {"error": str(e)})

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8765), Handler)
    print("VPN API запущен на порту 8765")
    server.serve_forever()
