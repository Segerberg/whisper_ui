import json
import os
import re

import ffmpeg
import torch
import whisper
from celery import Celery
from flask import Flask, render_template, request, send_from_directory
from flask_cors import CORS
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from whisper.utils import get_writer

from config import Config

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)
db = SQLAlchemy(app)
migrate = Migrate(app, db)


def make_celery(app):
    celery = Celery(app.import_name, broker=app.config['CELERY_BROKER_URL'],
                    backend=app.config['CELERY_RESULT_BACKEND'])
    # celery.conf.update(app.config)
    TaskBase = celery.Task

    class ContextTask(TaskBase):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)

    celery.Task = ContextTask
    return celery


celery = make_celery(app)


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


@celery.task(bind=True)
def transcribe(self, id, translate, m):
    torch.cuda.is_available()
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

    model = whisper.load_model(m, device=DEVICE, download_root="data")
    transcript = Transcripts.query.get(id)

    if translate:
        result = model.transcribe(f'uploads/{transcript.audiofile}', task="translate")
    else:
        result = model.transcribe(f'uploads/{transcript.audiofile}')

    writer = get_writer("all", str('data'))
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

    return render_template('index.html', transcripts=transcripts)


async def save_uploaded_file(file):
    upload_folder = 'uploads'
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
    btn = f'<button hx-swap="outerHTML" hx-post="/transcribe/{transcript.id}" class="btn btn-sm btn-outline-success float-end" style="margin-bottom:1em">Transcribe' \
          f'</button>'

    transcript_section = f'''
    <div id="transView" class="col-md-6">
        <h2>Transcribe</h2>
        <div class="card w-100" style="width: 18rem;">
            <div class="card-header">
            Options
            </div>
            <form>
            <div id="transmodel" class="card-body">       
            <h5>Model</h5>
            <select name="model" class="form-select" aria-label="Default select example">
                <option value="tiny">tiny</option>
                <option selected value="base">base</option>
                <option value="small">small</option>
                <option value="medium">medium</option>
                <option value="large">large</option>   
            </select>
            <h5>Options</h5>
            <div class="form-check form-switch">
            <input name="translate" class="form-check-input" type="checkbox" id="flexSwitchCheckDefault">
           <label class="form-check-label" for="flexSwitchCheckDefault">Translate</label>
           </div>
            </div>
            <div class="card-body">{btn}</div>
            </form>
        </div>
     </div>'''

    if transcript.result or transcript.transcribed:
        btn = f'<button hx-post="/transcribe/{transcript.id}" class="btn btn-sm btn-secondary" disabled>Transcribe</button>'
        if transcript.result:
            transcript_section = f'''
            <div id="transView" class="col-md-6">
                <h2>Transcript</h2>
                <div class="card w-100" style="width: 18rem;">
                    <div class="card-header">
                    Download
                    </div>
                    <div class="card-body">
                    <a href="/download_file/{os.path.splitext(transcript.audiofile)[0]}.vtt">VTT</a>
                    <br>
                    <a href="/download_file/{os.path.splitext(transcript.audiofile)[0]}.srt">SRT</a>
                    <br>
                    <a href="/download_file/{os.path.splitext(transcript.audiofile)[0]}.txt">TXT</a>
                    <br>
                    <a href="/download_file/{os.path.splitext(transcript.audiofile)[0]}.tsv">TSV</a>
                    <br>
                    <a href="/download_file/{os.path.splitext(transcript.audiofile)[0]}.json">JSON</a>
                    </div>

                </div>
                
             </div>'''
        else:
            transcript_section = f'''
            <div id="transView" class="col-md-6">
                <h2>Transcript</h2>
                <div class="card w-100" style="width: 18rem;">
                    <div class="card-header">
                    Actions
                    </div>
                    
                    <div class="card-body">
                    <h3 hx-trigger="every 5s" hx-get="/detail/{id}" hx-target="#detailView" hx-swap="outerHTML">Working....</h3>
                    <div class="d-flex justify-content-center"> <div class="lds-ripple" style="margin-top:2em"><div></div><div></div></div></div>
                    </div>
                    
                </div>
             </div>'''

    return f'''
    <div id="detailView" class="row">
        <div class="col-md-4">
        <h2>Metadata</h2>  
            <div class="card" w-100">
                <div class="card-header">
                    <span class="badge bg-primary">{transcript.audiofile}</span>
                </div>
                <ul class="list-group list-group-flush">
                    <li class="list-group-item"><strong>Duration:</strong> {transcript.duration}</li>
                    <li class="list-group-item"><strong>Codec:</strong> {transcript.codec}</li>
                    <li class="list-group-item"><strong>Encoder:</strong> {transcript.encoded_by} </li>
                    <li class="list-group-item"><strong>Sample rate:</strong> {transcript.sample_rate} </li>
                    <li class="list-group-item"><strong>Channels:</strong> {transcript.channels} </li>
                </ul>
            </div>
        </div>
        {transcript_section}
        </div>   
        '''


@app.route('/filestable', methods=['GET'])
def filestable():
    delete_btn = '<button hx-get="/delete/{i.id}" hx-swap="outerHTML" class="btn btn-sm btn-outline-danger">delete</button>'
    transcripts = Transcripts.query.all()
    if len(transcripts) == 0:
        return '<div class="d-flex justify-content-center" style="margin-top:2em"><h5>No files</h5></div>'
    tr_list = ['<tr><td>' \
               f'<a style="color: inherit;" hx-get="/detail/{i.id}" hx-target="#detailView" hx-swap="outerHTML" href="#">'
               '<img src="/static/img/file_audio.svg" height="20px"> ' + i.audiofile + f'</td>' \
                                                                                       '</a>' \
                                                                                       f'<td>' \
                                                                                       f'<button hx-get="/detail/{i.id}" hx-target="#detailView" hx-swap="outerHTML" class="btn btn-sm btn-outline-secondary">view</button>&nbsp;&nbsp;' \
                                                                                       f'<button hx-post="/delete/{i.id}" hx-target="#detailView" hx-swap="innerHTML"  settle:1s" hx-confirm="Delete?" class="btn btn-sm btn-outline-danger fade-me-out">delete</button>' \
                                                                                       f'</td></tr>' for i in
               transcripts]

    tr = ''.join(tr_list)
    html = f'''
    <table class="table">
    <thead>
    <th>Audiofile</th>
    <th>Actions</th>
    </thead>
    <tbody> 
    {tr}
    </tbody>
    </table>'''
    return html


async def delete_file(file):
    upload_folder = 'uploads'
    file_path = os.path.join(upload_folder, file)
    os.remove(file_path)
    transcript_files = os.listdir('data')

    for f in transcript_files:
        only_name = os.path.splitext(file)[0]
        if f.startswith(only_name):
            os.remove(os.path.join('data', f))


@app.route('/delete/<id>', methods=['POST'])
async def delete(id):
    transcript = Transcripts.query.get(id)
    filename = transcript.audiofile
    db.session.delete(transcript)
    db.session.commit()
    await delete_file(filename)
    return ''


@app.route('/download/<id>', methods=['POST'])
def download(id):
    transcript = Transcripts.query.get(id)
    ext = 'vtt'

    writer = get_writer("vtt", str('data'))
    writer(json.loads(transcript.result), str(transcript.audiofile))
    print(transcript.audiofile)
    return f'<div HX-Redirect="/download_file/{transcript.audiofile}"></div>'

    # return send_file(path_or_file=f"data/{u}.{ext}", as_attachment=True, download_name=f"transcript.txt")


@app.route('/download_file/<filename>', methods=['GET'])
def download_file(filename):
    return send_from_directory('data', filename, as_attachment=True)
