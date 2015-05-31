from waiter import app, isAlfredEncoding, APP_NAME
from utils import humansize
from flask import render_template

import mock

@app.route(APP_NAME + '/test2/')
def get_test2():
    fileDict = {'path': 'some/path/',
                'filename': 'a filename',
                'size': humansize(100000),
                'isAlfredEncoding': isAlfredEncoding('a filename')}
    files = [fileDict]
    return render_template("display.html",
                           title='testpage',
                           files=files)

