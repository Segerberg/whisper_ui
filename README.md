# whisper_ui

## Development

### Initate database

<pre>
flask db init
</pre>
<pre>
flask db migrate
</pre>
<pre>
flask db upgrade
</pre>


### Start celery worker
<pre>
celery -A app.celery worker --loglevel=info
</pre>

### Run development server
<pre>
flask run
</pre>


## Env
<pre>
FLASK_APP=app.py
FLASK_ENV=development
SECRET_KEY='My secret string'
CELERY_BROKER_URL='redis://default:redispw@localhost:55001'
CELERY_RESULT_BACKEND='redis://default:redispw@localhost:55001'
CORS = "*"
</pre>