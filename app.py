from flask import Flask, jsonify, request, render_template
import requests
import time

from database import get_connection

app = Flask(__name__)


# Home dashboard
@app.route("/")
def home():
    return render_template("dashboard.html")


# Get all registered APIs
@app.route("/api/services")
def get_services():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM api_services ORDER BY api_id DESC")
    services = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(services)


# Register a new API
@app.route("/api/add", methods=["POST"])
def add_api():
    data = request.json

    conn = get_connection()
    cursor = conn.cursor()

    query = """
        INSERT INTO api_services
        (api_name, endpoint_url, http_method, description)
        VALUES (%s, %s, %s, %s)
    """

    values = (
        data["api_name"],
        data["endpoint_url"],
        data.get("http_method", "GET"),
        data.get("description", "")
    )

    cursor.execute(query, values)
    conn.commit()

    api_id = cursor.lastrowid

    cursor.close()
    conn.close()

    return jsonify({
        "message": "API registered successfully",
        "api_id": api_id
    })


# Monitor a single API
@app.route("/api/check/<int:api_id>", methods=["POST"])
def check_api(api_id):

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM api_services WHERE api_id = %s",
        (api_id,)
    )

    api = cursor.fetchone()

    if not api:
        cursor.close()
        conn.close()

        return jsonify({"error": "API not found"}), 404

    if not api["is_active"]:
        cursor.close()
        conn.close()

        return jsonify({"error": "API is inactive"}), 400

    start_time = time.time()

    try:

        response = requests.request(
            method=api["http_method"],
            url=api["endpoint_url"],
            timeout=10
        )

        response_time = round(
            (time.time() - start_time) * 1000, 2
        )

        status_code = response.status_code

        if status_code < 400:
            status = "UP"
        else:
            status = "DOWN"

        error_message = None

    except requests.exceptions.RequestException as e:

        response_time = round(
            (time.time() - start_time) * 1000, 2
        )

        status_code = 0
        status = "DOWN"
        error_message = str(e)

    # Save monitoring result
    cursor.execute("""
        INSERT INTO request_logs
        (api_id, status_code, response_time_ms, error_message)
        VALUES (%s, %s, %s, %s)
    """, (
        api_id,
        status_code,
        response_time,
        error_message
    ))

    # Generate alert if API is down
    if status == "DOWN":

        cursor.execute("""
            INSERT INTO alerts
            (api_id, alert_type, severity, message)
            VALUES (%s, %s, %s, %s)
        """, (
            api_id,
            "API_FAILURE",
            "CRITICAL",
            f"{api['api_name']} is DOWN"
        ))

    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({
        "api_name": api["api_name"],
        "status": status,
        "status_code": status_code,
        "response_time_ms": response_time,
        "error": error_message
    })


# Monitor all registered APIs
@app.route("/api/check-all", methods=["POST"])
def check_all():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT api_id FROM api_services WHERE is_active = TRUE"
    )

    api_ids = cursor.fetchall()

    cursor.close()
    conn.close()

    results = []

    for row in api_ids:
        api_id = row[0]

        result = requests.post(
            f"http://127.0.0.1:5000/api/check/{api_id}"
        )

        results.append(result.json())

    return jsonify(results)


# Get recent request logs
@app.route("/api/logs")
def get_logs():

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT request_logs.*, api_services.api_name
        FROM request_logs
        JOIN api_services
        ON request_logs.api_id = api_services.api_id
        ORDER BY log_id DESC
        LIMIT 50
    """)

    logs = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(logs)


# Get alerts
@app.route("/api/alerts")
def get_alerts():

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT alerts.*, api_services.api_name
        FROM alerts
        JOIN api_services
        ON alerts.api_id = api_services.api_id
        ORDER BY alert_id DESC
        LIMIT 50
    """)

    alerts = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(alerts)


# Dashboard statistics
@app.route("/api/stats")
def get_stats():

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM api_services
    """)
    total = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS active
        FROM api_services
        WHERE is_active = TRUE
    """)
    active = cursor.fetchone()["active"]

    cursor.execute("""
        SELECT COUNT(*) AS total_alerts
        FROM alerts
        WHERE is_resolved = FALSE
    """)
    alerts = cursor.fetchone()["total_alerts"]

    cursor.execute("""
        SELECT AVG(response_time_ms) AS avg_response
        FROM request_logs
        WHERE status_code > 0
    """)
    avg_response = cursor.fetchone()["avg_response"]

    cursor.close()
    conn.close()

    return jsonify({
        "total_apis": total,
        "active_apis": active,
        "unresolved_alerts": alerts,
        "average_response_time": round(float(avg_response or 0), 2)
    })


if __name__ == "__main__":
    app.run(debug=True)