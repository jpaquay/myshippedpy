from fastapi import Fastapi

app = Fastapi(__name__)

@app.route("/")
def hello():
    return "Hello World!!"


if __name__ == "__main__":
    app.run(debug=True,host='0.0.0.0')
