# admin.py

from flask import Flask, request, redirect, url_for, render_template_string, session
from pyrogram import Client
from config import FLASK_USERNAME, FLASK_PASSWORD, BOT_TOKEN
from database import get_stats, get_recent_activity
import asyncio

app = Flask(__name__)
app.secret_key = "secret"  # Change this in production
pyro_client = Client("admin-bot", bot_token=BOT_TOKEN)

# HTML Templates
login_page = '''
<form method="post">
    <input type="text" name="username" placeholder="Username"/><br>
    <input type="password" name="password" placeholder="Password"/><br>
    <input type="submit" value="Login"/>
</form>
'''

admin_panel = '''
<h2>Welcome, Admin</h2>
<p>Total Users: {{ users }}</p>
<p>Total Downloads: {{ downloads }}</p>
<form action="/broadcast" method="post" enctype="multipart/form-data">
    <textarea name="text" placeholder="Message to broadcast"></textarea><br>
    <input type="submit" value="Send Broadcast"/>
</form>
<h3>Recent Downloads</h3>
<ul>
{% for row in activity %}
    <li>User: {{ row[0] }} | File: {{ row[1] }} | Time: {{ row[2] }}</li>
{% endfor %}
</ul>
<a href="/logout">Logout</a>
'''

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == FLASK_USERNAME and request.form["password"] == FLASK_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
    return login_page

@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        return redirect("/")
    users, downloads = get_stats()
    activity = get_recent_activity()
    return render_template_string(admin_panel, users=users, downloads=downloads, activity=activity)

@app.route("/broadcast", methods=["POST"])
def broadcast():
    if not session.get("logged_in"):
        return redirect("/")
    message = request.form["text"]
    asyncio.run(send_broadcast(message))
    return "Broadcast sent."

@app.route("/logout")
def logout():
    session["logged_in"] = False
    return redirect("/")

async def send_broadcast(text):
    await pyro_client.start()
    users, _ = get_stats()
    for user_id in range(1, users + 1):
        try:
            await pyro_client.send_message(user_id, text)
        except:
            continue
    await pyro_client.stop()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)