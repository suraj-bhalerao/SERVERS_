import os
import time
import json
import requests
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

UPLOAD_DIR = "/home/pi/logs_to_upload"
SERVER_URL = "http://<server-ip>:8000/upload_chunk/"
USER = "pi-board-01"
UPLOAD_LOG = "/home/pi/upload_log.json"
CRON_LOG = "/home/pi/cron_activity.log"
RETENTION_DAYS = 7
CHUNK_SIZE = 512 * 1024

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def load_upload_log():
    return json.load(open(UPLOAD_LOG)) if os.path.exists(UPLOAD_LOG) else {}

def save_upload_log(log_data):
    with open(UPLOAD_LOG, "w") as f:
        json.dump(log_data, f, indent=2)

def is_file_being_written(file_path):
    try:
        with open(file_path, 'a'):
            return False
    except:
        return True

def upload_file(file_path, upload_log):
    if str(file_path) in upload_log:
        return "Already uploaded"

    if is_file_being_written(file_path):
        return "File is still open (write-locked)"

    with open(file_path, 'rb') as f:
        files = {'file': (file_path.name, f, 'text/plain')}
        data = {'user': USER}
        try:
            res = requests.post(SERVER_URL, files=files, data=data)
            if res.status_code == 200:
                upload_log[str(file_path)] = str(datetime.now())
                return "Uploaded"
            else:
                return f"Failed (HTTP {res.status_code})"
        except Exception as e:
            return f"Failed ({e})"


def upload_file_chunked(file_path, upload_log):
    if str(file_path) in upload_log:
        return "Already uploaded"

    if is_file_being_written(file_path):
        return "File is still open (write-locked)"

    file_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file_path.name}"
    file_size = os.path.getsize(file_path)
    total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE

    with open(file_path, 'rb') as f:
        for i in range(total_chunks):
            chunk = f.read(CHUNK_SIZE)
            headers = {
                "X-File-ID": file_id,
                "X-Chunk-Index": str(i),
                "X-Total-Chunks": str(total_chunks),
                "X-User": USER,
                "X-Chunk-Hash": sha256(chunk)
            }
            files = {'chunk': ("chunk", chunk)}
            try:
                r = requests.post(SERVER_URL, headers=headers, files=files)
                r.raise_for_status()
            except Exception as e:
                return f"Failed chunk {i}: {e}"

    upload_log[str(file_path)] = str(datetime.now())
    return "Uploaded"

def delete_old_files(upload_log):
    now = datetime.now()
    deleted = []
    for file_str in list(upload_log):
        file_path = Path(file_str)
        if file_path.exists() and (now - datetime.fromtimestamp(file_path.stat().st_mtime)).days >= RETENTION_DAYS:
            try:
                file_path.unlink()
                deleted.append(file_str)
                del upload_log[file_str]
            except:
                pass
    return deleted

def log_activity(message):
    with open(CRON_LOG, "a") as logf:
        logf.write(f"{datetime.now()}: {message}\n")

def main():
    upload_log = load_upload_log()
    for file_path in Path(UPLOAD_DIR).rglob("*.log"):
        result = upload_file_chunked(file_path, upload_log)
        log_activity(f"{file_path.name}: {result}")
    for f in delete_old_files(upload_log):
        log_activity(f"Deleted old file: {f}")
    save_upload_log(upload_log)

if __name__ == "__main__":
    main()