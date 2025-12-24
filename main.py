from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import psycopg2
import bcrypt
import requests
import time

app = Flask(__name__)
CORS(app)

# --- DATABASE CONFIGURATION ---
DB_CONFIG = {
    "dbname": "load_tester",
    "user": "postgres",
    "password": "akshar",
    "host": "localhost",
    "port": "5433"
}


def get_db_connection():
    try:
        return psycopg2.connect(**DB_CONFIG)
    except:
        return None


# --- ROUTES ---

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/signup', methods=['POST'])
def signup():
    data = request.json
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        hashed = bcrypt.hashpw(data['password'].encode('utf-8'), bcrypt.gensalt())
        cur.execute("INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
                    (data['username'], data['email'], hashed.decode('utf-8')))
        conn.commit()
        return jsonify({"message": "Signup successful!"})
    except:
        return jsonify({"error": "User exists"}), 400


@app.route('/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db_connection()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cur = conn.cursor()
    cur.execute("SELECT id, password_hash, username FROM users WHERE email=%s", (data['email'],))
    user = cur.fetchone()

    if user and bcrypt.checkpw(data['password'].encode('utf-8'), user[1].encode('utf-8')):
        return jsonify({"user_id": user[0], "username": user[2]})
    else:
        return jsonify({"error": "Invalid credentials"}), 401


@app.route('/load-test', methods=['POST'])
def load_test():
    data = request.json
    url = data['url']
    if not url.startswith('http'): url = 'https://' + url
    total = int(data['requests'])

    success = 0
    total_time = 0
    request_times = []

    for i in range(total):
        try:
            start = time.time()
            r = requests.get(url, timeout=3)
            time_taken = time.time() - start
            total_time += time_taken
            request_times.append(round(time_taken, 3))
            if r.status_code == 200: success += 1
        except:
            request_times.append(0)
            pass

    avg_time = round((total_time / total) if total > 0 else 0, 4)
    success_pct = round((success / total) * 100, 2)

    if data.get('user_id'):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO test_history (user_id, url, total_requests, success_percentage, avg_response_time) VALUES (%s,%s,%s,%s,%s)",
            (data['user_id'], url, total, success_pct, avg_time))
        conn.commit()

    return jsonify({
        "url": url,
        "success": success_pct,
        "time": avg_time,
        "history": request_times
    })


@app.route('/compare', methods=['POST'])
def compare_sites():
    data = request.json
    urls = [data['url1'], data['url2']]

    # Get request count from frontend, default to 5 if missing
    req_count = int(data.get('requests', 5))

    results = []

    for url in urls:
        if not url.startswith('http'): url = 'https://' + url
        site_times = []

        # Run dynamic number of requests
        for _ in range(req_count):
            try:
                start = time.time()
                requests.get(url, timeout=3)
                site_times.append(round(time.time() - start, 3))
            except:
                site_times.append(0)

        avg_time = round(sum(site_times) / len(site_times), 3) if site_times else 0

        results.append({
            "url": url,
            "avg_time": avg_time,
            "times": site_times
        })

    return jsonify(results)


@app.route('/history', methods=['POST'])
def get_history():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT url, success_percentage, avg_response_time, tested_at FROM test_history WHERE user_id=%s ORDER BY tested_at DESC LIMIT 20",
        (data['user_id'],))
    rows = cur.fetchall()

    history = [{"url": r[0], "success": r[1], "time": r[2], "date": r[3].strftime("%Y-%m-%d")} for r in rows]
    return jsonify(history)


if __name__ == '__main__':
    app.run(debug=True, port=5000)