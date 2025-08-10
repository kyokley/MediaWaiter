from .settings import DEBUG, PORT, HOST
from .waiter import app


def main():
    app.debug = DEBUG
    if not DEBUG:
        app.run(host=HOST, port=PORT)
    else:
        app.run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    main()
