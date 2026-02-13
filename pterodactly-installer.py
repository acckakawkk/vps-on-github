#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
from pathlib import Path

PANEL_DIR = Path("/var/www/pterodactyl")
PHP_VER = "8.3"

def ask(label: str) -> str:
    while True:
        v = input(f"[ + ] Masukan {label} : ").strip()
        if v:
            return v
        print("[ + ] Input tidak boleh kosong")

def run(args, cwd=None):
    subprocess.run(args, check=True, text=True, cwd=cwd)

def capture(args) -> str:
    return subprocess.check_output(args, text=True).strip()

def detect_ip() -> str:
    try:
        out = capture(["bash", "-lc", "command -v tailscale >/dev/null 2>&1 && tailscale ip -4 | head -n 1 || true"])
        if out:
            return out
    except Exception:
        pass
    try:
        out = capture(["bash", "-lc", "ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i==\"src\") {print $(i+1); exit}}' || true"])
        if out:
            return out
    except Exception:
        pass
    try:
        return capture(["bash", "-lc", "hostname -I 2>/dev/null | awk '{print $1}' || true"])
    except Exception:
        return ""

def sql_lit(s: str) -> str:
    return s.replace("'", "''")

def set_env_kv(env_path: Path, key: str, value: str):
    lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    found = False
    out = []
    for ln in lines:
        if ln.startswith(key + "="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")

def write_file(path: str, content: str):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")

def main():
    if os.geteuid() != 0:
        print("[ + ] Jalankan sebagai root: sudo -i lalu python3 install_panel.py")
        sys.exit(1)

    panel_user = ask("username panel")
    panel_pass = ask("password panel")
    panel_email = ask("email panel")
    timezone = ask("timezone")
    db_name = panel_user
    db_user = panel_user
    db_pass = panel_pass

    run(["bash", "-lc", f"timedatectl set-timezone '{timezone}' || true"])

    run(["apt-get", "update", "-y"])
    run(["apt-get", "install", "-y", "curl", "ca-certificates", "gnupg", "lsb-release", "tar", "unzip", "git", "software-properties-common", "apt-transport-https"])

    run(["apt-get", "install", "-y", "nginx", "mariadb-server", "redis-server"])
    run(["systemctl", "enable", "--now", "nginx"])
    run(["systemctl", "enable", "--now", "mariadb"])
    run(["systemctl", "enable", "--now", "redis-server"])

    run(["bash", "-lc", "LC_ALL=C.UTF-8 add-apt-repository -y ppa:ondrej/php || true"])
    run(["apt-get", "update", "-y"])
    run([
        "apt-get", "install", "-y",
        f"php{PHP_VER}", f"php{PHP_VER}-cli", f"php{PHP_VER}-fpm", f"php{PHP_VER}-gd",
        f"php{PHP_VER}-mysql", f"php{PHP_VER}-mbstring", f"php{PHP_VER}-bcmath", f"php{PHP_VER}-xml",
        f"php{PHP_VER}-curl", f"php{PHP_VER}-zip", f"php{PHP_VER}-intl"
    ])

    run(["bash", "-lc", "curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer"])

    run(["mariadb", "-e", f"CREATE DATABASE IF NOT EXISTS {db_name};"])
    run(["mariadb", "-e", f"CREATE USER IF NOT EXISTS '{sql_lit(db_user)}'@'127.0.0.1' IDENTIFIED BY '{sql_lit(db_pass)}';"])
    run(["mariadb", "-e", f"GRANT ALL PRIVILEGES ON {db_name}.* TO '{sql_lit(db_user)}'@'127.0.0.1' WITH GRANT OPTION;"])
    run(["mariadb", "-e", "FLUSH PRIVILEGES;"])

    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    run(["bash", "-lc", f"cd '{PANEL_DIR}' && curl -L https://github.com/pterodactyl/panel/releases/latest/download/panel.tar.gz | tar -xz"])
    run(["bash", "-lc", f"cd '{PANEL_DIR}' && chmod -R 755 storage/* bootstrap/cache/"])

    ip = detect_ip()
    if not ip:
        print("[ + ] Gagal mendeteksi IP. Pastikan jaringan/Tailscale aktif.")
        sys.exit(1)

    app_url = f"http://{ip}"

    env_path = PANEL_DIR / ".env"
    if not env_path.exists():
        shutil.copyfile(PANEL_DIR / ".env.example", env_path)

    set_env_kv(env_path, "APP_URL", app_url)
    set_env_kv(env_path, "APP_TIMEZONE", timezone)
    set_env_kv(env_path, "DB_HOST", "127.0.0.1")
    set_env_kv(env_path, "DB_DATABASE", db_name)
    set_env_kv(env_path, "DB_USERNAME", db_user)
    set_env_kv(env_path, "DB_PASSWORD", db_pass)
    set_env_kv(env_path, "CACHE_DRIVER", "redis")
    set_env_kv(env_path, "QUEUE_CONNECTION", "redis")
    set_env_kv(env_path, "SESSION_DRIVER", "redis")
    set_env_kv(env_path, "REDIS_HOST", "127.0.0.1")

    run(["bash", "-lc", "COMPOSER_ALLOW_SUPERUSER=1 composer install --no-dev --optimize-autoloader"], cwd=str(PANEL_DIR))

    run(["php", "artisan", "key:generate", "--force"], cwd=str(PANEL_DIR))
    run(["php", "artisan", "migrate", "--seed", "--force"], cwd=str(PANEL_DIR))

    run([
        "php", "artisan", "p:user:make",
        f"--email={panel_email}",
        f"--username={panel_user}",
        f"--name-first={panel_user}",
        "--name-last=dev",
        f"--password={panel_pass}",
        "--admin=1"
    ], cwd=str(PANEL_DIR))

    run(["bash", "-lc", f"chown -R www-data:www-data '{PANEL_DIR}'"])

    run(["bash", "-lc", "rm -f /etc/nginx/sites-enabled/default || true"])
    nginx_conf = f"""server {{
  listen 80;
  server_name _;
  root {PANEL_DIR}/public;
  index index.php;

  location / {{
    try_files $uri $uri/ /index.php?$query_string;
  }}

  location ~ \\.php$ {{
    include snippets/fastcgi-php.conf;
    fastcgi_pass unix:/run/php/php{PHP_VER}-fpm.sock;
  }}

  location ~ /\\.ht {{
    deny all;
  }}
}}
"""
    write_file("/etc/nginx/sites-available/pterodactyl.conf", nginx_conf)
    run(["bash", "-lc", "ln -sf /etc/nginx/sites-available/pterodactyl.conf /etc/nginx/sites-enabled/pterodactyl.conf"])
    run(["systemctl", "restart", f"php{PHP_VER}-fpm"])
    run(["systemctl", "restart", "nginx"])

    run(["bash", "-lc", f"(crontab -l 2>/dev/null | grep -v '{PANEL_DIR}/artisan schedule:run' || true; echo '* * * * * php {PANEL_DIR}/artisan schedule:run >> /dev/null 2>&1') | crontab -"])
    service = f"""[Unit]
Description=Pterodactyl Queue Worker
After=redis-server.service

[Service]
User=www-data
Group=www-data
Restart=always
ExecStart=/usr/bin/php {PANEL_DIR}/artisan queue:work --queue=high,standard,low --sleep=3 --tries=3
StartLimitInterval=180
StartLimitBurst=30
RestartSec=5s

[Install]
WantedBy=multi-user.target
"""
    write_file("/etc/systemd/system/pteroq.service", service)
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", "pteroq.service"])

    print("")
    print(f"Penginstalan panel selesai, Akses di : {app_url}")
    print("")
    print(f"USERNAME : {panel_user} PASSWORD : {panel_pass} EMAIL : {panel_email}")
    print("")

if __name__ == "__main__":
    main()
