from webcore import create_web

app = create_web()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
