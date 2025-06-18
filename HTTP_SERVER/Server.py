from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
import shutil
import uuid
from loguru import logger
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import FileResponse, HTMLResponse

# FastAPI app
app = FastAPI()

# Configuration
UPLOAD_DIR = "uploaded_logs"
TEMP_CHUNKS_DIR = "temp_chunks"
LOG_FILE = "logs/server.log"
DATABASE_URL = "sqlite:///server.db"
templates = Jinja2Templates(directory="templates")

# Logging setup
logger.add(LOG_FILE, rotation="1 MB", retention="10 days", level="INFO")

# Ensure upload directory exists
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(TEMP_CHUNKS_DIR, exist_ok=True)
os.makedirs("logs", exist_ok=True)
logger.add(LOG_FILE, rotation="1 MB", retention="10 days", level="INFO")

# FastAPI app
app = FastAPI()

# Database setup
Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

class LogEntry(Base):
    __tablename__ = "log_entries"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, unique=True)
    original_filename = Column(String)
    user = Column(String)
    timestamp = Column(DateTime)

Base.metadata.create_all(bind=engine)

# Routes
# ==== This is the basic uploder ===
@app.post("/upload/")
async def upload_log_file(user: str = Form(...), file: UploadFile = File(...)):
    if not file.filename.endswith(".log"):
        logger.warning(f"Rejected non-.log file upload attempt: {file.filename}")
        raise HTTPException(status_code=400, detail="Only .log files are allowed")

    unique_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    db = SessionLocal()
    try:
        entry = LogEntry(
            filename=unique_filename,
            original_filename=file.filename,
            user=user,
            timestamp=datetime.utcnow()
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        logger.info(f"Uploaded by {user}: {file.filename} -> {unique_filename}")
        return {"message": "File uploaded successfully", "metadata": {
            "filename": unique_filename,
            "user": user,
            "timestamp": entry.timestamp.isoformat()
        }}
    finally:
        db.close()

# === This is the chunk by chunk uploader route
@app.post("/upload_chunk/")
async def upload_chunk(
    chunk: UploadFile,
    x_file_id: str = Header(...),
    x_chunk_index: int = Header(...),
    x_total_chunks: int = Header(...),
    x_chunk_hash: str = Header(...),
    x_user: str = Header(...)
):
    file_subdir = os.path.join(TEMP_CHUNKS_DIR, x_file_id)
    os.makedirs(file_subdir, exist_ok=True)
    chunk_path = os.path.join(file_subdir, f"{x_chunk_index}.part")

    content = await chunk.read()
    if hashlib.sha256(content).hexdigest() != x_chunk_hash:
        raise HTTPException(status_code=400, detail="Hash mismatch")

    with open(chunk_path, "wb") as f:
        f.write(content)

    parts = sorted(os.listdir(file_subdir), key=lambda x: int(x.split(".")[0]))
    if len(parts) == x_total_chunks:
        final_path = os.path.join(UPLOAD_DIR, x_file_id)
        with open(final_path, "wb") as final:
            for part in parts:
                with open(os.path.join(file_subdir, part), "rb") as p:
                    final.write(p.read())
        shutil.rmtree(file_subdir)
        db = SessionLocal()
        try:
            entry = LogEntry(
                filename=x_file_id,
                original_filename=x_file_id.split("_", 1)[-1],
                user=x_user,
                timestamp=datetime.utcnow()
            )
            db.add(entry)
            db.commit()
        finally:
            db.close()
        return {"status": "complete", "message": f"{x_file_id} fully uploaded"}

    return {"status": "incomplete", "chunk_index": x_chunk_index}

# @app.get("/logs/")
# def get_all_logs():
#     db = SessionLocal()
#     try:
#         entries = db.query(LogEntry).all()
#         return [{
#             "id": e.id,
#             "filename": e.filename,
#             "original_filename": e.original_filename,
#             "user": e.user,
#             "timestamp": e.timestamp.isoformat()
#         } for e in entries]
#     finally:
#         db.close()

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    db = SessionLocal()
    try:
        logs = db.query(LogEntry).order_by(LogEntry.timestamp.desc()).all()
        return templates.TemplateResponse("dashboard.html", {"request": request, "logs": logs})
    finally:
        db.close()

@app.get("/view/{filename}", response_class=HTMLResponse)
def view_log_file(request: Request, filename: str):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(file_path, "r") as f:
        content = f.read()
    return HTMLResponse(f"""
    <html><body>
    <h2>Viewing: {filename}</h2>
    <pre>{content}</pre>
    <a href="/">Back to dashboard</a>
    </body></html>
    """)

@app.get("/download/{filename}")
def download_log_file(filename: str):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path, filename=filename, media_type='text/plain')
