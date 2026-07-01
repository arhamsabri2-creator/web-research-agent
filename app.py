from flask import Flask, render_template, request, jsonify
from openai import OpenAI
from tavily import TavilyClient
from twilio.rest import Client
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import os
import json
import sqlite3
from datetime import datetime

load_dotenv()

app = Flask(__name__)

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

def init_db():
    conn = sqlite3.connect("research.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT,
        report TEXT,
        created_at TEXT
    )''')
    conn.commit()
    conn.close()

def save_report(topic, report):
    conn = sqlite3.connect("research.db")
    c = conn.cursor()
    c.execute("INSERT INTO reports (topic, report, created_at) VALUES (?, ?, ?)",
              (topic, report, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

def get_all_reports():
    conn = sqlite3.connect("research.db")
    c = conn.cursor()
    c.execute("SELECT id, topic, created_at FROM reports ORDER BY id DESC")
    reports = c.fetchall()
    conn.close()
    return reports

def get_report_by_id(report_id):
    conn = sqlite3.connect("research.db")
    c = conn.cursor()
    c.execute("SELECT topic, report, created_at FROM reports WHERE id=?", (report_id,))
    report = c.fetchone()
    conn.close()
    return report

tools = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for information on a topic",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

def search_web(query):
    results = tavily_client.search(query=query, max_results=3)
    content = ""
    for r in results["results"]:
        content += f"Title: {r['title']}\nContent: {r['content']}\n\n"
    return content

def send_whatsapp(report, topic):
    message = f"Research Report: {topic}\n\n{report[:1500]}"
    twilio_client.messages.create(
        body=message,
        from_=os.getenv("TWILIO_WHATSAPP_NUMBER"),
        to="whatsapp:+919161832926"
    )

def run_agent(topic):
    current_year = datetime.now().year
    messages = [
        {
            "role": "system",
            "content": f"You are a research agent. Today's year is {current_year}. Always search for the most recent and latest information available. When searching, always include the current year in your search queries to get fresh results. Once you have enough information, provide a clear detailed summary mentioning how recent the information is."
        },
        {
            "role": "user",
            "content": f"Research this topic thoroughly using the most recent information available in {current_year}: {topic}"
        }
    ]

    while True:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )

        message = response.choices[0].message
        messages.append(message)

        if not message.tool_calls:
            return message.content

        for tool_call in message.tool_calls:
            if tool_call.function.name == "search_web":
                args = json.loads(tool_call.function.arguments)
                result = search_web(args["query"])
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })

def scheduled_research():
    topic = "Latest AI news and developments today"
    result = run_agent(topic)
    save_report(topic, result)
    send_whatsapp(result, topic)

scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_research, "cron", hour=8, minute=0)
scheduler.start()

init_db()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/research", methods=["POST"])
def research():
    topic = request.json.get("topic")
    result = run_agent(topic)
    save_report(topic, result)
    send_whatsapp(result, topic)
    return jsonify({"result": result})

@app.route("/history")
def history():
    reports = get_all_reports()
    return render_template("history.html", reports=reports)

@app.route("/report/<int:report_id>")
def view_report(report_id):
    report = get_report_by_id(report_id)
    return render_template("report.html", report=report)

@app.route("/get_history")
def get_history():
    reports = get_all_reports()
    return jsonify({"reports": reports})

@app.route("/get_report/<int:report_id>")
def get_report(report_id):
    report = get_report_by_id(report_id)
    return jsonify({"report": report[1]})

if __name__ == "__main__":
    app.run(debug=True)