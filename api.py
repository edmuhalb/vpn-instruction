#!/usr/bin/env python3
import subprocess
import json
import os
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# ── Конфигурация сервера ──────────────────────────────────────────
SERVER_IP       = "194.226.169.15"
SERVER_PORT     = "37930"
SUBNET          = "10.8.1"
CONF_PATH       = "/opt/amnezia/awg/awg0.conf"
CONTAINER       = "amnezia-awg2"
API_SECRET      = "vpn-secret-2024"   # поменяй на свой

# AmneziaWG параметры (из конфига сервера)
AWG_PARAMS = {
    "Jc": "4", "Jmin": "10", "Jmax": "50",
    "S1": "147", "S2": "29", "S3": "21", "S4": "6",
    "H1": "1209694282", "H2": "1816253784",
    "H3": "1999736174", "H4": "2099948346"
}

def docker_exec(cmd):
    result = subprocess.run(
        ["docker", "exec", CONTAINER] + cmd,
        capture_output=True, text=True
    )
    return result.stdout.strip()

def docker_exec_input(cmd, stdin_data):
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER] + cmd,
        input=stdin_data, capture_output=True, text=True
    )
    return result.stdout.strip()

def get_server_pubkey():
    privkey = None
    conf = docker_exec(["cat", CONF_PATH])
    for line in conf.splitlines():
        if line.startswith("PrivateKey"):
            privkey = line.split("=", 1)[1].strip()
            break
    if not privkey:
        return None
    return docker_exec_input(["awg", "pubkey"], privkey)

def get_next_ip():
    conf = docker_exec(["cat", CONF_PATH])
    used = []
    for line in conf.splitlines():
        m = re.search(r'AllowedIPs\s*=\s*10\.8\.1\.(\d+)', line)
        if m:
            used.append(int(m.group(1)))
    for i in range(2, 255):
        if i not in used:
            return f"{SUBNET}.{i}"
    return None

def get_preshared_key():
    conf = docker_exec(["cat", CONF_PATH])
    for line in conf.splitlines():
        if line.startswith("PresharedKey"):
            return line.split("=", 1)[1].strip()
    return docker_exec(["awg", "genpsk"])

def create_user(name):
    # Генерируем ключи клиента
    client_privkey = docker_exec(["awg", "genkey"])
    client_pubkey  = docker_exec_input(["awg", "pubkey"], client_privkey)
    preshared_key  = get_preshared_key()
    client_ip      = get_next_ip()
    server_pubkey  = get_server_pubkey()

    if not client_ip:
        return None, "Нет свободных IP-адресов"
    if not server_pubkey:
        return None, "Не удалось получить публичный ключ сервера"

    # Добавляем пир в конфиг сервера
    peer_block = f"\n[Peer]\n# {name}\nPublicKey = {client_pubkey}\nPresharedKey = {preshared_key}\nAllowedIPs = {client_ip}/32\n"
    
    # Записываем в конфиг
    subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", f"echo '{peer_block}' >> {CONF_PATH}"],
    )

    # Применяем без разрыва соединений
    docker_exec(["awg", "addconf", "awg0", CONF_PATH])
    subprocess.run(["docker", "exec", CONTAINER, "awg", "set", "awg0",
        "peer", client_pubkey,
        "preshared-key", "/dev/stdin",
        "allowed-ips", f"{client_ip}/32"],
        input=preshared_key, text=True
    )

    # Формируем клиентский конфиг (AmneziaWG формат)
    client_conf = f"""[Interface]
PrivateKey = {client_privkey}
Address = {client_ip}/24
DNS = 1.1.1.1, 8.8.8.8
Jc = {AWG_PARAMS['Jc']}
Jmin = {AWG_PARAMS['Jmin']}
Jmax = {AWG_PARAMS['Jmax']}
S1 = {AWG_PARAMS['S1']}
S2 = {AWG_PARAMS['S2']}
S3 = {AWG_PARAMS['S3']}
S4 = {AWG_PARAMS['S4']}
H1 = {AWG_PARAMS['H1']}
H2 = {AWG_PARAMS['H2']}
H3 = {AWG_PARAMS['H3']}
H4 = {AWG_PARAMS['H4']}

[Peer]
PublicKey = {server_pubkey}
PresharedKey = {preshared_key}
Endpoint = {SERVER_IP}:{SERVER_PORT}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""
    # Формируем Amnezia URL (vpn://base64(json))
    import json, base64
    amnezia_json = {
        "containers": [{
            "awg": {
                "H1": AWG_PARAMS["H1"], "H2": AWG_PARAMS["H2"],
                "H3": AWG_PARAMS["H3"], "H4": AWG_PARAMS["H4"],
                "Jc": AWG_PARAMS["Jc"], "Jmin": AWG_PARAMS["Jmin"],
                "Jmax": AWG_PARAMS["Jmax"],
                "S1": AWG_PARAMS["S1"], "S2": AWG_PARAMS["S2"],
                "S3": AWG_PARAMS["S3"], "S4": AWG_PARAMS["S4"],
                "last_config": client_conf
            },
            "container": "amnezia-awg"
        }],
        "defaultContainer": "amnezia-awg",
        "description": f"VPN ({name})",
        "dns1": "1.1.1.1",
        "dns2": "8.8.8.8",
        "hostName": SERVER_IP,
        "port": SERVER_PORT,
        "splitTunnelSites": [],
        "splitTunnelType": 0
    }
    encoded = base64.urlsafe_b64encode(json.dumps(amnezia_json).encode()).decode()
    vpn_url = f"vpn://{encoded}"

    return client_conf, vpn_url, None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # отключаем лишние логи

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Secret")

    def do_GET(self):
        if self.path != "/users":
            self.send_response(404)
            self.end_headers()
            return

        secret = self.headers.get("X-Secret", "")
        if secret != API_SECRET:
            self.send_response(403)
            self.send_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Forbidden"}).encode())
            return

        conf = docker_exec(["cat", CONF_PATH])
        users = []
        current = {}
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

        # Get active peers from awg show
        try:
            awg_show = docker_exec(["awg", "show", "awg0"])
            active_keys = set()
            for l in awg_show.splitlines():
                if "latest handshake" in l.lower():
                    pass
                if l.strip().startswith("peer:"):
                    active_keys.add(l.strip().split("peer:")[1].strip())
            for u in users:
                u["active"] = u.get("pubkey", "") in active_keys
        except:
            pass

        self.send_response(200)
        self.send_cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"users": users}).encode())

    def do_DELETE(self):
        if self.path != "/users":
            self.send_response(404)
            self.end_headers()
            return

        secret = self.headers.get("X-Secret", "")
        if secret != API_SECRET:
            self.send_response(403)
            self.send_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Forbidden"}).encode())
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        pubkey = body.get("pubkey", "").strip()

        if not pubkey:
            self.send_response(400)
            self.send_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "pubkey required"}).encode())
            return

        # Remove peer from live WireGuard
        subprocess.run(["docker", "exec", CONTAINER, "awg", "set", "awg0", "peer", pubkey, "remove"])

        # Remove peer block from config file
        conf = docker_exec(["cat", CONF_PATH])
        lines = conf.splitlines()
        new_lines = []
        skip = False
        for line in lines:
            if line.strip() == "[Peer]":
                # Look ahead to check if this peer has our pubkey
                skip = False
                new_lines.append(("PEER_MARKER", []))
            elif skip:
                continue
            elif line.strip().startswith("PublicKey") and pubkey in line:
                # Remove last PEER_MARKER block
                for i in range(len(new_lines)-1, -1, -1):
                    if new_lines[i] == ("PEER_MARKER", []):
                        new_lines = new_lines[:i]
                        break
                skip = True
            else:
                if new_lines and isinstance(new_lines[-1], tuple):
                    peer_marker = new_lines.pop()
                    new_lines.append("[Peer]")
                new_lines.append(line)

        # Flush remaining PEER_MARKER
        result = []
        for l in new_lines:
            if isinstance(l, tuple):
                result.append("[Peer]")
            else:
                result.append(l)

        new_conf = "\n".join(result)
        subprocess.run(
            ["docker", "exec", "-i", CONTAINER, "sh", "-c", f"cat > {CONF_PATH}"],
            input=new_conf, text=True
        )

        self.send_response(200)
        self.send_cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors()
        self.end_headers()

    def do_POST(self):
        if self.path != "/create":
            self.send_response(404)
            self.end_headers()
            return

        # Проверяем секрет
        secret = self.headers.get("X-Secret", "")
        if secret != API_SECRET:
            self.send_response(403)
            self.send_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Forbidden"}).encode())
            return

        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length))
        name   = body.get("name", "user").strip() or "user"

        conf, vpn_url, err = create_user(name)

        self.send_response(200)
        self.send_cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()

        if err:
            self.wfile.write(json.dumps({"error": err}).encode())
        else:
            self.wfile.write(json.dumps({"config": conf, "url": vpn_url, "name": name}).encode())


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8765), Handler)
    print("VPN API запущен на порту 8765")
    server.serve_forever()
