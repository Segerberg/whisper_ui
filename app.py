import logging
import time

from flask import Flask, abort, request
from celery import Celery

from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
migrate = Migrate(app, db)

def make_celery(app):
    celery = Celery(app.import_name, broker=app.config['CELERY_BROKER_URL'], backend=app.config['CELERY_RESULT_BACKEND'])
    #celery.conf.update(app.config)
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
    text = db.Column(db.String(128))


@celery.task(bind=True)
def insert_db(self, inp):
    with app.app_context():
        text = Transcripts(text=inp)
        db.session.add(text)
        db.session.commit()
        #db.session.close()
    return text


@app.route("/")
def index():
    x = insert_db.delay("Test")
    return {"result_id": x.id}
