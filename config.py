import os
basedir = os.path.abspath(os.path.dirname(__file__))


class Config(object):
    # ...
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get('SECRET_KEY')
    FLASK_APP_BRAND = os.environ.get('FLASK_APP_BRAND')
    CORS = os.environ.get('CORS')
    CELERY_BROKER_URL = 'redis://:redispw@localhost:32773'
    CELERY_RESULT_BACKEND = 'redis://:redispw@localhost:32773'
