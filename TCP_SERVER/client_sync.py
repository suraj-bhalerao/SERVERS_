import socket
import os
import hashlib
import time
import sqlite3
import logging
from pathlib import Path

# Configuration
SERVER_IP = '103.80.163.32'  # Replace with your server’s public IP or DDNS
PORT = 5001
CLIENT_ID = 'rpi-001'  # Unique for each client
LOG_ROOT = '/logs'
RETRIES = 3
DB_PATH = 'sent_files.db'

# Logging setup
logging.basicConfig(filename='client.log', level=logging.INFO, format='%(asctime)s - %(message)s')

# SQLite DB for tracking sent files
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS sent (
    path TEXT PRIMARY KEY,
    timestamp TEXT,
    checksum TEXT
)''')
conn.commit()

def is_sent(rel_path):
    c.execute('SELECT 1 FROM sent WHERE path = ?', (rel_path,))
    return c.fetchone() is not None

def mark_sent(rel_path, checksum):
    c.execute('INSERT OR REPLACE INTO sent (path, timestamp, checksum) VALUES (?, datetime("now"), ?)', (rel_path, checksum))
    conn.commit()

def sha256sum(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

def send_file(local_path, relative_path):
    checksum = sha256sum(local_path)
    header = f"{CLIENT_ID}|{relative_path}|{checksum}".ljust(1024)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((SERVER_IP, PORT))
        s.sendall(header.encode())

        with open(local_path, 'rb') as f:
            while chunk := f.read(1024):
                s.sendall(chunk)

        response = s.recv(1024).decode().strip()
        if response.startswith('ACK'):
            logging.info(f"[✓] Sent and confirmed: {relative_path}")
            mark_sent(relative_path, checksum)
        else:
            raise Exception(f"Server NAK: {response}")

def scan_and_send():
    for path in Path(LOG_ROOT).rglob("*.log"):
        rel_path = path.relative_to(LOG_ROOT).as_posix()
        full_path = str(path)
        if is_sent(rel_path):
            continue

        for attempt in range(1, RETRIES + 1):
            try:
                logging.info(f"[>] Attempting to send: {rel_path}")
                send_file(full_path, rel_path)
                break
            except Exception as e:
                logging.warning(f"[!] Failed {rel_path}, attempt {attempt}: {e}")
                time.sleep(2)

scan_and_send()
