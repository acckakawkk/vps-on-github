#!/usr/bin/env python3
import os
import sys
import subprocess
from pathlib import Path
from getpass import getpass

def run(args, cwd=None):
    subprocess.run(args, check=True, text=True, cwd=cwd)

def out(cmd: str) -> str:
    return subprocess.check_output(["bash", "-lc", cmd], text=True).strip()

def ensure_root():
    if os.geteuid() != 0:
        print("[ + ] Jalankan sebagai root: sudo -i lalu python3 wings_auto.py")
        sys.exit(1)

def detect_tailscale_ip() -> str:
    try:
        return out("command -v tailscale >/dev/null 2>&1 && tailscale ip -4 | head -n 1 || true").strip()
    except Exception:
        return ""

def detect_vps_ip() -> str:
    try:
        ip = out("ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i==\"src\") {print $(i+1); exit}}' || true").strip()
        if ip:
            return ip
    except Exception:
        pass
    try:
        return out("hostname -I 2>/dev/null | awk '{print $1}' || true").strip()
    except Exception:
        return ""

def panel_url_auto() -> str:
    ts = detect_tailscale_ip()
    if ts:
        return f"http://{ts}"
    ip = detect_vps_ip()
    if ip:
        return f"http://{ip}"
    return "http://127.0.0.1"

def install_docker():
    run(["apt-get", "update", "-y"])
    run(["apt-get", "install", "-y", "ca-certificates", "curl", "gnupg", "lsb-release", "apt-transport-https"])
    run(["bash", "-lc", "install -m 0755 -d /etc/apt/keyrings"])
    run(["bash", "-lc", "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg"])
    run(["bash", "-lc", "chmod a+r /etc/apt/keyrings/docker.gpg"])
    run(["bash", "-lc",
         'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] '
         'https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" '
         '> /etc/apt/sources.list.d/docker.list'
    ])
    run(["apt-get", "update", "-y"])
    run(["apt-get", "install", "-y", "docker-ce", "docker-ce-cli", "containerd.io"])
    run(["systemctl", "enable", "--now", "docker"])

def install_wings():
    Path("/etc/pterodactyl").mkdir(parents=True, exist_ok=True)
    run(["bash", "-lc", "curl -L -o /usr/local/bin/wings https://github.com/pterodactyl/wings/releases/latest/download/wings_linux_amd64"])
    run(["chmod", "+x", "/usr/local/bin/wings"])

def ensure_service():
    svc = Path("/etc/systemd/system/wings.service")
    if not svc.exists():
        svc.write_text(
            "[Unit]\n"
            "Description=Pterodactyl Wings Daemon\n"
            "After=docker.service\n"
            "Requires=docker.service\n\n"
            "[Service]\n"
            "User=root\n"
            "LimitNOFILE=4096\n"
            "ExecStart=/usr/local/bin/wings\n"
            "Restart=on-failure\n"
            "RestartSec=5s\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n",
            encoding="utf-8"
        )
        run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", "wings"])

def check_configure():
    h = ""
    try:
        h = out("/usr/local/bin/wings --help")
    except Exception:
        pass
    if "configure" not in h:
        print("[ + ] Wings kamu tidak mendukung 'wings configure'.")
        print("[ + ] Jalankan: /usr/local/bin/wings --help")
        sys.exit(1)

def main():
    ensure_root()

    token = getpass("[ + ] Masukan token ptla : ").strip()
    if not token:
        print("[ + ] Token kosong")
        sys.exit(1)

    node_id = os.environ.get("NODE_ID", "1").strip()
    if not node_id.isdigit():
        node_id = "1"

    panel_url = os.environ.get("PANEL_URL", "").strip() or panel_url_auto()

    install_docker()
    install_wings()
    ensure_service()
    check_configure()

    run(["/usr/local/bin/wings", "configure", "--panel-url", panel_url, "--token", token, "--node", node_id], cwd="/etc/pterodactyl")
    run(["systemctl", "restart", "wings"])

    print("")
    print("Wings selesai")
    print(f"Panel URL : {panel_url}")
    print(f"Node ID   : {node_id}")
    try:
        tsip = detect_tailscale_ip()
        if tsip:
            print(f"IP TS     : {tsip}")
    except Exception:
        pass
    print("")

if __name__ == "__main__":
    main()
