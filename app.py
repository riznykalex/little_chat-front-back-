from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from flask_socketio import SocketIO, send, emit
import os
import sqlite3

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # вимкнути кешування статичних файлів
app.jinja_env.cache = None  # вимкнути кеш Jinja2

socketio = SocketIO(app)

# Запобігання кешуванню HTML
@app.after_request
def set_no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response

# --- База даних SQLite ---
def init_db():
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    # створюємо таблицю з полями для зображень
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user TEXT,
                    text TEXT,
                    timestamp TEXT,
                    image TEXT
                )''')
    # додати колонку image у старі бази, якщо її немає
    c.execute("PRAGMA table_info(messages)")
    cols = [row[1] for row in c.fetchall()]
    if 'timestamp' not in cols:
        c.execute("ALTER TABLE messages ADD COLUMN timestamp TEXT")
    if 'image' not in cols:
        c.execute("ALTER TABLE messages ADD COLUMN image TEXT")
    conn.commit()
    conn.close()

init_db()

# --- Чат ---
# коли клієнт підключається, віддаємо історію
@socketio.on('connect')
def handle_connect():
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("SELECT user, text, timestamp, image FROM messages ORDER BY id")
    rows = c.fetchall()
    conn.close()
    history = [{'user': r[0], 'text': r[1], 'timestamp': r[2], 'image': r[3]} for r in rows]
    # надсилаємо тільки клієнту
    socketio.emit('history', history)


@socketio.on('message')
def handle_message(data):
    # data expected to be dict with user and text
    user = data.get('user', 'User')
    text = data.get('text', '')
    image = data.get('image', None)
    timestamp = data.get('timestamp') or __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Зберігаємо повідомлення в БД
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("INSERT INTO messages (user, text, timestamp, image) VALUES (?, ?, ?, ?)", (user, text, timestamp, image))
    conn.commit()
    conn.close()
    # надсилаємо словник назад
    send({'user': user, 'text': text, 'timestamp': timestamp, 'image': image}, broadcast=True)

@socketio.on('message-deleted')
def handle_message_deleted(data):
    # передаємо всім клієнтам інформацію про видалене повідомлення
    emit('message-deleted', {'timestamp': data.get('timestamp')}, broadcast=True)

# --- Файли ---
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не знайдено'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Файл не вибрано'})
    
    # Перевірка типу файлу
    allowed_extensions = {'.jpg', '.jpeg', '.png'}
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in allowed_extensions:
        return jsonify({'success': False, 'error': 'Дозволені тільки jpg та png файли'})
    
    # Генеруємо уніквальну назву
    import time
    unique_filename = f"{int(time.time())}_{file.filename}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    
    try:
        file.save(filepath)
        user = request.form.get('user', 'Анонім')
        return jsonify({
            'success': True,
            'filename': unique_filename,
            'user': user
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/files/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- Видалення повідомлень ---
@app.route('/delete-message', methods=['POST'])
def delete_message():
    data = request.get_json()
    timestamp = data.get('timestamp')
    
    if not timestamp:
        return jsonify({'success': False, 'error': 'Timestamp не знайдений'})
    
    try:
        conn = sqlite3.connect('chat.db')
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE timestamp = ?", (str(timestamp),))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# --- Головна сторінка ---
@app.route('/')
def index():
    return render_template('index.html')


if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
