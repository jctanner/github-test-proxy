#!/usr/bin/env python


import argparse
import datetime
import glob
import gzip
import hashlib
import json
import os
import pickle
import random
import requests
import six
import subprocess
import time

from logzero import logger
from pprint import pprint
from flask import Flask
from flask import jsonify
from flask import request

from github_test_proxy.cacher import ProxyCacher


GM = ProxyCacher()
app = Flask(__name__)


########################################################
#   ROUTES
########################################################


@app.route('/rate_limit')
def rate_limit():
    reset = int(time.time()) + 10
    rl = {
        'resources': {
            'core': {
                'limit': 5000,
                'remaining': 5000,
                'reset': reset
            }
        },
        'rate': {
            'limit': 5000,
            'remaining': 5000,
            'reset': reset
        }
    }
    return jsonify(rl)



@app.route('/<path:path>', methods=['GET', 'POST', 'DELETE', 'UPDATE'])
def abstract_path(path):

    # 127.0.0.1 - - [12/Apr/2019 13:54:04] "GET /repos/ansible/ansible/git/commits/6a7ba80b421da4e3fe70badb67c1164e6ea5d75e HTTP/1.1" 200 -
    # 127.0.0.1 - - [12/Apr/2019 13:54:06] "DELETE /repos/ansible/ansible/issues/55055/labels/needs_revision HTTP/1.1" 405 -

    logger.info('# ABSTRACT PATH! - %s' % path)
    path_parts = path.split('/')
    logger.info(six.text_type((len(path_parts),path_parts)))
    logger.info(request.path)

    # context defines the baseurl
    thiscontext = None
    if path_parts[0] in ['jobs', 'runs']:
        thiscontext = 'api.shippable.com'
    else:
        thiscontext = 'api.github.com'

    # tell the mocker what the real url should be
    thisurl = request.url.replace(
            'http://localhost:5000',
            'https://%s' % thiscontext
    )
    logger.debug('thisurl: %s' % thisurl)
    headers, data = GM.cached_tokenized_request(
        thisurl,
        method=request.method.upper(),
        data=request.data,
        context=thiscontext
    )

    pprint(data)

    resp = jsonify(data)
    whitelist = ['ETag', 'Link']
    for k,v in headers.items():
        if not k.startswith('X-') and k not in whitelist:
            continue
        resp.headers.set(k, v)
    #pprint(dict(resp.headers))
    return resp


def main():

    action_choices = [
        'load',  # use fixtures but do not make requests
        'proxy', # make requests and cache results
        'smart', # use fixtures when possible
    ]

    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=action_choices,
        help="which mode to run the proxy in")
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--token', '--github_token', default=None)
    parser.add_argument('--shippable_token', default=None)
    parser.add_argument('--fixtures', '--fixturedir',
        default='/tmp/github.proxy/fixtures',
        help="where the fixtures are stored and loaded from")
    parser.add_argument('--deltas', '--deltadir',
        default='/tmp/github/deltas',
        help="where to store changes from POST data")
    args = parser.parse_args()

    GM.deltadir = os.path.expanduser(args.deltas)
    GM.fixturedir = os.path.expanduser(args.fixtures)

    if args.action == 'proxy':
        GM.proxy = True
        GM.usecache = False
        GM.TOKEN = args.token
        GM.SHIPPABLE_TOKEN = args.shippable_token
    elif args.action == 'smart':
        GM.proxy = True
        GM.usecache = True
        GM.TOKEN = args.token
        GM.SHIPPABLE_TOKEN = args.shippable_token

    else:
        GM.proxy = False
        GM.usecache = True
        GM.writedeltas = True

    app.run(debug=args.debug, host='0.0.0.0')


if __name__ == "__main__":
    main()
