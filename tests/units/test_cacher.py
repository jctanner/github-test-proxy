#!/usr/bin/env python3

import datetime
import json
import os
import tempfile
from unittest.mock import patch

from github_proxy.cacher import ProxyCacher


###############################################################################
#   HELPERS 
###############################################################################

class RequestsMocker:
    _headers = {}
    _data = {}
    _get_calls = 0
    def get(self, url, headers=None):
        self._get_calls += 1
        return MockRequestsResponse(
            self._headers[url],
            self._data[url]
        )


class MockRequestsResponse:
    _headers = None
    _json = None
    def __init__(self, inheaders, injson):
        self._headers = inheaders
        self._json = injson
    def json(self):
        return self._json
    @property
    def headers(self):
        return self._headers

###############################################################################
#   TESTS
###############################################################################

def test_init():
    GM = ProxyCacher()


def test_cached_tokenized_request_get():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch('github_proxy.proxy.requests', RequestsMocker()) as mock_requests:
            GM = ProxyCacher()
            GM.proxy = True
            GM.fixturedir = os.path.join(tmpdir, 'fixtures')
            GM.deltadir = os.path.join(tmpdir, 'deltas')

            url = 'https://api.github.com/repos/ansible/ansible/issues/1'
            mock_requests._headers[url] = {}
            mock_requests._data[url] = {
                    'number': 1,
                    'url': url
            }

            rheaders, rdata = GM.cached_tokenized_request(url, context='api.github.com')
            print(rdata)
            print(GM.fixturedir)

            assert mock_requests._get_calls == 1
            assert isinstance(rdata, dict)
            assert rdata.get('number') == 1
            assert rdata.get('url').endswith('ansible/ansible/issues/1')

            checkfiles = [
                os.path.join(
                    GM.fixturedir,
                    'api.github.com',
                    'repos',
                    'ansible',
                    'ansible',
                    'issues',
                    '1.json.gz'
                ),
                os.path.join(
                    GM.fixturedir,
                    'api.github.com',
                    'repos',
                    'ansible',
                    'ansible',
                    'issues',
                    '1.headers.json.gz'
                )
            ]

            for checkfile in checkfiles:
                assert os.path.exists(checkfile)


def test_cached_tokenized_request_post():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch('github_proxy.proxy.requests', RequestsMocker()) as mock_requests:
            GM = ProxyCacher()
            GM.proxy = True
            GM.fixturedir = os.path.join(tmpdir, 'fixtures')
            GM.deltadir = os.path.join(tmpdir, 'deltas')

            ts = datetime.datetime.now().isoformat()
            url = 'https://api.github.com/repos/ansible/ansible/issues/1'
            mock_requests._headers[url] = {}
            mock_requests._data[url] = {
                    'number': 1,
                    'url': url,
                    'created_at': ts,
                    'update_at': ts,
                    'comments': 0
            }

            rheaders, rdata = GM.cached_tokenized_request(url, context='api.github.com')
            print(rdata)
            print(GM.fixturedir)

            comments_url = url + '/comments'
            comment = {
                'body': 'feefiifofum'
            }
            GM.cached_tokenized_request(
                comments_url,
                data=json.dumps(comment),
                method='POST'
            )

            #GM.proxy = False
            GM.loaded = True
            GM.usecache = True
            rheaders2, rdata2 = GM.cached_tokenized_request(
                url,
                context='api.github.com'
            )
            print(rdata2)
            #import epdb; epdb.st()

            assert rdata2['updated_at'] > ts
            assert rdata2['comments'] == 1


def test_replace_data_urls():
    pass
