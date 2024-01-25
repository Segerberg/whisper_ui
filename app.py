import json
import os
import re

import ffmpeg
import torch
import whisper
from celery import Celery, current_task
from flask import Flask, render_template, request, send_from_directory, redirect, url_for
from flask_cors import CORS
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from whisper.utils import get_writer
import whisper.transcribe
import sys
import redis

import tqdm
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)
db = SQLAlchemy(app)
migrate = Migrate(app, db)

def calculate_percentage(progress, total):
    if total == 0:
        return 0
    return (progress / total) * 100



def make_celery(app):
    celery = Celery(app.import_name, broker=app.config['CELERY_BROKER_URL'],
                    backend=app.config['CELERY_RESULT_BACKEND'])
    TaskBase = celery.Task

    class ContextTask(TaskBase):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)

    celery.Task = ContextTask
    return celery


celery = make_celery(app)
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0)


class Transcripts(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    audiofile = db.Column(db.Text)
    codec = db.Column(db.String)
    sample_rate = db.Column(db.String)
    channels = db.Column(db.String)
    encoded_by = db.Column(db.String)
    duration = db.Column(db.String)
    transcribed = db.Column(db.Boolean)
    result = db.Column(db.Text)
    progress = db.Column(db.Text)


@celery.task(bind=True)
def transcribe(self, id, translate, m):
    torch.cuda.is_available()
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    model = whisper.load_model(m, device=DEVICE, download_root="/data/models")
    transcript = Transcripts.query.get(id)
    os.makedirs('/data/transcripts', exist_ok=True)

    if translate:
        result = model.transcribe(f'/data/uploads/{transcript.audiofile}', task="translate")
    else:
        result = model.transcribe(f'/data/uploads/{transcript.audiofile}')

    writer = get_writer("all", str('/data/transcripts'))
    writer(json.loads(json.dumps(result)), str(transcript.audiofile))

    transcript.result = json.dumps(result)
    db.session.commit()


def sanitize_filename(filename):
    # Remove any non-alphanumeric characters and spaces
    filename = re.sub(r'[^\w\s.-]', '', filename)
    # Replace spaces with underscores
    filename = filename.replace(' ', '_')
    return filename


def format_duration(duration):
    hours, remainder = divmod(duration, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"


def get_audio_metadata(file_path):
    probe = ffmpeg.probe(file_path, v='error', select_streams='a:0', show_entries='format=duration')
    stream = probe['streams'][0]

    metadata = {
        "codec": stream.get('codec_long_name', 'N/A'),
        "sample_rate": stream.get('sample_rate', 'N/A'),
        "channels": stream.get('channels', 'N/A'),
        "encoded_by": 'N/A',
        "duration": 'N/A'

    }
    try:
        encoded_by = probe['format']['tags'].get('encoded_by', 'N/A')
        metadata['encoded_by'] = encoded_by
    except KeyError:
        pass
    duration = probe['format'].get('duration')
    if duration:
        metadata['duration'] = format_duration(float(duration))

    return metadata


@app.route("/", methods=["GET"])
async def index():
    transcripts = Transcripts.query.all()
    allowed_filetypes = os.getenv("ALLOWED_FILETYPES") or ".mp3"
    max_file_size = os.getenv("MAXFILESIZE") or 500

    return render_template('index.html', transcripts=transcripts,
                           allowed_filetypes=allowed_filetypes,
                           max_file_size=max_file_size)


async def save_uploaded_file(file):
    upload_folder = '/data/uploads'
    os.makedirs(upload_folder, exist_ok=True)
    safe_filename = secure_filename(file.filename)
    safe_filename = sanitize_filename(safe_filename)

    file_path = os.path.join(upload_folder, safe_filename)

    with open(file_path, 'wb') as f:
        f.write(file.read())

    metadata = get_audio_metadata(file_path)
    transcript = Transcripts(audiofile=safe_filename, codec=metadata['codec'], duration=metadata['duration'],
                             channels=metadata['channels'], sample_rate=metadata['sample_rate'],
                             encoded_by=metadata['encoded_by'])

    db.session.add(transcript)
    db.session.commit()


@app.route('/upload', methods=['POST'])
async def upload_file():
    if 'file' not in request.files:
        return 'No file part'

    file = request.files['file']
    if file.filename == '':
        return 'No selected file'

    await save_uploaded_file(file)
    return 'File uploaded successfully'


@app.route('/transcribe/<id>', methods=['POST'])
def transcribe_audio(id):
    translate = request.form.get('translate')
    model = request.form.get('model')
    transcript = Transcripts.query.get(id)
    transcript.transcribed = True
    db.session.commit()
    transcribe.delay(id, translate, model)
    btn = f'<img hx-trigger="every 5s" hx-get="/detail/{id}" hx-target="#detailView" hx-swap="outerHTML" src=/static/img/pulse-rings-multiple.svg class="float-end style="margin-bottom:2em">'
    return btn


@app.route('/detail/<id>', methods=['GET'])
def detail(id):
    transcript = Transcripts.query.get(id)
    transcripts_file_path = None
    if transcript.result:
        transcripts_file_path = os.path.splitext(transcript.audiofile)[0]

    return render_template('detail.html', transcript=transcript, id=id, transcripts_file_path=transcripts_file_path)



@app.route('/filestable', methods=['GET'])
def filestable():
    transcripts = Transcripts.query.all()
    return render_template('_filestable.html', transcripts=transcripts)


async def delete_file(file):
    upload_folder = '/data/uploads'
    file_path = os.path.join(upload_folder, file)
    os.remove(file_path)
    transcript_files = os.listdir('/data/transcripts')

    for f in transcript_files:
        only_name = os.path.splitext(file)[0]
        if f.startswith(only_name):
            os.remove(os.path.join('/data/transcripts', f))


@app.route('/delete/<id>', methods=['POST'])
async def delete(id):
    transcript = Transcripts.query.get(id)
    filename = transcript.audiofile
    db.session.delete(transcript)
    db.session.commit()
    await delete_file(filename)
    return ''



@app.route('/download_file/<filename>', methods=['GET'])
def download_file(filename):
    return send_from_directory('/data/transcripts', filename, as_attachment=True)
