import subprocess
import json
import os
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from flask_cors import CORS
import psycopg2
import bcrypt
import requests
import time
import concurrent.futures
from datetime import datetime

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


# --- HELPER: RUN LIGHTHOUSE ---
def run_lighthouse_audit(url):
    try:
        command = [
            'lighthouse', url,
            '--output=json',
            '--output-path=stdout',
            '--quiet',
            '--chrome-flags="--headless --disable-gpu --no-sandbox"'
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        data = json.loads(result.stdout)
        cats = data['categories']
        return {
            "performance": int(cats['performance']['score'] * 100),
            "accessibility": int(cats['accessibility']['score'] * 100),
            "seo": int(cats['seo']['score'] * 100),
            "best_practices": int(cats['best-practices']['score'] * 100)
        }
    except Exception as e:
        print(f"Lighthouse Error: {e}")
        return None


# --- HELPER: ANALYZE RESULTS ---
def analyze_results(success_pct, avg_time, test_type, audit_scores=None):
    status = "Good"
    problem = "None detected."
    solution = "System is healthy."

    if success_pct < 90:
        status = "Critical"
        problem = "High failure rate (HTTP 500/Timeout)."
        solution = "Check server logs, database connections, and memory usage."
    elif avg_time > 2.0:
        status = "Poor"
        problem = "High Latency (> 2s response)."
        solution = "Optimize database queries, use caching (Redis), or upgrade server CPU."
    elif avg_time > 1.0:
        status = "Medium"
        problem = "Moderate Latency."
        solution = "Minify assets and check for unoptimized loops in backend code."

    if test_type == 'bug' and success_pct < 100:
        status = "Critical"
        problem = "Broken Links or API Errors found."
        solution = "Review 404/500 error logs and fix broken routes."

    if test_type == 'all' and audit_scores:
        if audit_scores['performance'] < 50:
            status = "Poor"
            problem = f"Lighthouse Performance is low ({audit_scores['performance']})."
            solution = "Reduce unused JS/CSS, optimize images, and enable text compression."

    return status, problem, solution


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
        conn.close()
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
    conn.close()

    if user and bcrypt.checkpw(data['password'].encode('utf-8'), user[1].encode('utf-8')):
        return jsonify({"user_id": user[0], "username": user[2]})
    else:
        return jsonify({"error": "Invalid credentials"}), 401


# --- STREAMING TEST ROUTE (UPDATED) ---
@app.route('/stream-test')
def stream_test():
    url = request.args.get('url')
    user_requests_count = int(request.args.get('requests', 10))
    test_type = request.args.get('test_type', 'stress')
    user_id = request.args.get('user_id')

    if not url.startswith('http'): url = 'https://' + url

    def run_request(u, timeout=5):
        try:
            start = time.time()
            r = requests.get(u, timeout=timeout)
            dur = time.time() - start
            return {"time": round(dur, 3), "status": r.status_code, "ok": r.status_code == 200}
        except:
            return {"time": 0, "status": "ERR", "ok": False}

    def generate():
        total_time_accum = 0
        total_success = 0
        total_reqs_run = 0
        chart_data = []

        # Dictionary to store results of specific phases for "Test All"
        phase_results = {}

        # --- LOGIC FOR "TEST ALL" ---
        if test_type == 'all':
            phases = [
                ("Stress Test", 5, 5),
                ("Spike Test", 5, 1),
                ("Concurrent Test", 5, 5),
                ("Endurance Test", 5, 5),
                ("Bug Scanner", 5, 5)
            ]

            global_iter = 1

            for phase_name, req_count, timeout in phases:
                yield f"data: {json.dumps({'type': 'log', 'msg': f'--- Starting {phase_name} ---'})}\n\n"

                phase_times = []
                phase_ok = 0

                if phase_name == "Concurrent Test":
                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        futures = [executor.submit(run_request, url, timeout) for _ in range(req_count)]
                        for future in concurrent.futures.as_completed(futures):
                            res = future.result()
                            phase_times.append(res['time'])
                            if res['ok']: phase_ok += 1

                            total_reqs_run += 1
                            if res['ok']: total_success += 1
                            total_time_accum += res['time']
                            chart_data.append(res['time'])

                            yield f"data: {json.dumps({'type': 'progress', 'iter': global_iter, 'time': res['time'], 'status': res['status'], 'is_ok': res['ok']})}\n\n"
                            global_iter += 1
                else:
                    for _ in range(req_count):
                        res = run_request(url, timeout)
                        phase_times.append(res['time'])
                        if res['ok']: phase_ok += 1

                        total_reqs_run += 1
                        if res['ok']: total_success += 1
                        total_time_accum += res['time']
                        chart_data.append(res['time'])

                        yield f"data: {json.dumps({'type': 'progress', 'iter': global_iter, 'time': res['time'], 'status': res['status'], 'is_ok': res['ok']})}\n\n"
                        global_iter += 1

                        if phase_name == "Endurance Test":
                            time.sleep(0.2)

                            # CALC PHASE STATS
                avg = sum(phase_times) / len(phase_times) if phase_times else 0
                p_min = min(phase_times) if phase_times else 0
                p_max = max(phase_times) if phase_times else 0
                pct = (phase_ok / req_count) * 100
                status = "PASS" if pct >= 90 else "FAIL"

                phase_results[phase_name] = {
                    "status": status,
                    "avg": round(avg, 3),
                    "min": round(p_min, 3),
                    "max": round(p_max, 3),
                    "score": int(pct)
                }
                yield f"data: {json.dumps({'type': 'log', 'msg': f'{phase_name} Completed: {status} (Avg: {round(avg, 3)}s)'})}\n\n"

        # --- LOGIC FOR SINGLE TEST TYPES ---
        else:
            for i in range(user_requests_count):
                to = 1 if test_type == 'spike' else 5
                res = run_request(url, to)
                total_reqs_run += 1
                if res['ok']: total_success += 1
                total_time_accum += res['time']
                chart_data.append(res['time'])

                yield f"data: {json.dumps({'type': 'progress', 'iter': i + 1, 'time': res['time'], 'status': res['status'], 'is_ok': res['ok']})}\n\n"

                if test_type == 'endurance':
                    time.sleep(0.5)

        # --- AUDIT (Test All Only) ---
        audit_scores = None
        if test_type == 'all':
            yield f"data: {json.dumps({'type': 'log', 'msg': 'Running Lighthouse Audit...'})}\n\n"
            audit_scores = run_lighthouse_audit(url)

        # --- FINAL CALCS ---
        final_avg = round((total_time_accum / total_reqs_run) if total_reqs_run > 0 else 0, 4)
        final_pct = round((total_success / total_reqs_run) * 100, 2)
        final_min = round(min(chart_data), 3) if chart_data else 0
        final_max = round(max(chart_data), 3) if chart_data else 0

        status, problem, solution = analyze_results(final_pct, final_avg, test_type, audit_scores)

        # DB Save
        if user_id and user_id != 'null':
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO test_history (user_id, url, total_requests, success_percentage, avg_response_time) VALUES (%s,%s,%s,%s,%s)",
                    (user_id, url, total_reqs_run, final_pct, final_avg))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"DB Error: {e}")

        # Send Final Packet
        final_data = {
            "type": "done",
            "total_reqs": total_reqs_run,
            "success_pct": final_pct,
            "avg_time": final_avg,
            "min_time": final_min,
            "max_time": final_max,
            "status": status,
            "problem": problem,
            "solution": solution,
            "audit": audit_scores,
            "history": chart_data,
            "phase_results": phase_results
        }
        yield f"data: {json.dumps(final_data)}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/compare', methods=['POST'])
def compare_sites():
    data = request.json
    urls = [data['url1'], data['url2']]
    req_count = int(data.get('requests', 5))
    results = []
    for url in urls:
        if not url.startswith('http'): url = 'https://' + url
        site_times = []
        for _ in range(req_count):
            try:
                start = time.time()
                requests.get(url, timeout=3)
                site_times.append(round(time.time() - start, 3))
            except:
                site_times.append(0)
        avg_time = round(sum(site_times) / len(site_times), 3) if site_times else 0
        lh = run_lighthouse_audit(url)
        if not lh: lh = {"performance": 0}
        results.append({"url": url, "avg_time": avg_time, "times": site_times, "lighthouse_perf": lh['performance']})
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
    conn.close()
    return jsonify([{"url": r[0], "success": r[1], "time": r[2], "date": r[3].strftime("%Y-%m-%d")} for r in rows])


if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=True)
