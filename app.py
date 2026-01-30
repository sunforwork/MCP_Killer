import os
import uuid
from functools import wraps

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename

from models import SessionLocal, Task, init_db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
APP_PASSWORD = os.environ.get("APP_PASSWORD")
if not APP_PASSWORD:
    raise RuntimeError("APP_PASSWORD must be set")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    app.secret_key = os.urandom(24)
    print("[!] SECRET_KEY not set; using a temporary key.")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=int(os.environ.get("MAX_CONTENT_LENGTH", 200 * 1024 * 1024)),
)
if os.environ.get("SESSION_COOKIE_SECURE") == "1":
    app.config["SESSION_COOKIE_SECURE"] = True


def ensure_dirs() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)


init_db()
ensure_dirs()


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"error": "unauthorized"}), 401
        return func(*args, **kwargs)

    return wrapper


@app.get("/")
def index():
    return render_template("index.html", authenticated=session.get("authenticated", False))


@app.post("/login")
def login():
    password = request.form.get("password", "")
    if password == APP_PASSWORD:
        session["authenticated"] = True
        return redirect(url_for("index"))
    return render_template(
        "index.html", authenticated=False, error="Invalid credentials"
    ), 401


@app.post("/logout")
def logout():
    session.pop("authenticated", None)
    return redirect(url_for("index"))


@app.post("/upload")
@login_required
def upload():
    uploaded_file = request.files.get("file")
    task_type = request.form.get("task_type", "").lower()
    if not uploaded_file or uploaded_file.filename == "":
        return jsonify({"error": "file is required"}), 400
    if task_type not in {"pack", "unpack"}:
        return jsonify({"error": "invalid task type"}), 400

    ensure_dirs()
    filename = secure_filename(uploaded_file.filename) or "upload"
    if task_type == "unpack" and not filename.lower().endswith(".mcpk"):
        return jsonify({"error": "mcpk file required"}), 400
    if task_type == "pack" and not filename.lower().endswith(".zip"):
        return jsonify({"error": "zip file required"}), 400

    task_id = str(uuid.uuid4())
    input_path = os.path.join(UPLOAD_DIR, f"{task_id}_{filename}")
    try:
        uploaded_file.save(input_path)
    except OSError as exc:
        if os.path.exists(input_path):
            os.remove(input_path)
        return jsonify({"error": f"upload failed: {exc}"}), 500

    with SessionLocal() as db:
        task = Task(
            id=task_id,
            task_type=task_type,
            status="pending",
            progress=0,
            message="Queued",
            log="",
            input_file=input_path,
        )
        db.add(task)
        db.commit()

    return jsonify({"task_id": task_id})


@app.get("/status/<task_id>")
@login_required
def status(task_id: str):
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            return jsonify({"error": "not found"}), 404

        log_tail = (task.log or "")[-5000:]
        download_url = None
        if task.status == "completed" and task.output_file and os.path.exists(task.output_file):
            download_url = url_for("download", task_id=task.id)

        return jsonify(
            {
                "id": task.id,
                "status": task.status,
                "progress": task.progress,
                "message": task.message,
                "log": log_tail,
                "download_url": download_url,
            }
        )


@app.get("/download/<task_id>")
@login_required
def download(task_id: str):
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task or task.status != "completed" or not task.output_file:
            abort(404)
        output_path = task.output_file

    if not os.path.exists(output_path):
        abort(404)
    return send_file(output_path, as_attachment=True)


if __name__ == "__main__":
    init_db()
    ensure_dirs()
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=int(os.environ.get("PORT", 5000)))
