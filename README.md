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