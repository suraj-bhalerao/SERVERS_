import socket
import threading
import os
import hashlib
import logging

# Server configuration
HOST = '0.0.0.0'
PORT = 5001
BASE_DIR = 'received_logs'

# Logging setup
logging.basicConfig(
    filename='server.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def sha256sum(file_path):
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

def recv_full(conn, length):
    """Receive exactly `length` bytes from the socket."""
    data = b''
    while len(data) < length:
        more = conn.recv(length - len(data))
        if not more:
            raise ConnectionError("Socket connection broken while reading header")
        data += more
    return data

def handle_client(conn, addr):
    try:
        header_bytes = recv_full(conn, 1024)
        header = header_bytes.decode().strip()
        logging.debug(f"Received header: {repr(header)}")

        parts = header.split('|')
        if len(parts) != 3:
            raise ValueError(f"Malformed header: {header}")

        client_id, relative_path, expected_hash = parts
        client_dir = os.path.join(BASE_DIR, client_id)
        target_path = os.path.join(client_dir, relative_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        if os.path.exists(target_path):
            logging.info(f"[SKIP] File exists: {target_path}")
            conn.sendall(b'NAK: File already exists')
            return

        # Receive file data
        with open(target_path, 'wb') as f:
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                f.write(data)

        # Verify checksum
        actual_hash = sha256sum(target_path)
        if actual_hash != expected_hash:
            logging.warning(f"[CORRUPT] {target_path} hash mismatch. Deleting.")
            os.remove(target_path)
            conn.sendall(b'NAK: Hash mismatch')
        else:
            logging.info(f"[RECEIVED] {client_id}: {relative_path}")
            conn.sendall(b'ACK')

    except Exception as e:
        logging.error(f"[ERROR] While handling {addr}: {e}")
        try:
            conn.sendall(b'NAK: Server error')
        except:
            pass
    finally:
        conn.close()

# Main server loop
if __name__ == "__main__":
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen()
        print(f"[+] Server running on {HOST}:{PORT}")
        logging.info(f"Server started on {HOST}:{PORT}")
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
