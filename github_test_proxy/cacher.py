#!/usr/bin/env python


import datetime
import glob
import gzip
import hashlib
import json
import os
import subprocess

import requests
from logzero import logger


BASEURL = 'http://localhost:5000'
ERROR_TIMER = 0

TOKENS = {
    'AAA': 'ansibot'
}

ANSIBLE_PROJECT_ID = u'573f79d02a8192902e20e34b'
SHIPPABLE_URL = u'https://api.shippable.com'
ANSIBLE_PROVIDER_ID = u'562dbd9710c5980d003b0451'
ANSIBLE_RUNS_URL = u'%s/runs?projectIds=%s&isPullRequest=True' % (
    SHIPPABLE_URL,
    ANSIBLE_PROJECT_ID
)

DEFAULT_ETAG = 'a00049ba79152d03380c34652f2cb612'

# https://elasticread.eng.ansible.com/ansible-issues/_search
# https://elasticread.eng.ansible.com/ansible-pull-requests/_search
#	?q=lucene_syntax_here
#	_search accepts POST

########################################################
#   MOCK
########################################################

class RequestNotCachedException(Exception):
    pass


def get_timestamp():
    # 2018-10-15T21:21:48.150184
    # 2018-10-10T18:25:49Z
    ts = datetime.datetime.now().isoformat()
    ts = ts.split('.')[0]
    ts += 'Z'
    return ts


def run_command(cmd):
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (so, se) = p.communicate()
    return (p.returncode, so, se)


def read_gzip_json(cfile):
    try:
        with gzip.open(cfile, 'r') as f:
            jdata = json.loads(f.read())
    except json.decoder.JSONDecodeError as e:
        logger.error(e)
        import epdb; epdb.st()
    return jdata

def write_gzip_json(cfile, data):
    with gzip.open(cfile, 'wb') as f:
        f.write(json.dumps(data).encode('utf-8'))


class ProxyCacher:

    TOKEN = None
    SHIPPABLE_TOKEN = None

    # make remote calls to github for uncached data
    proxy = False

    # use local ondisk cache from fixtures+deltas
    usecache = False

    # where to store and load the data fetched from github
    fixturedir = '/tmp/bot.fixtures'

    # where to store the new events created by POST
    deltadir = '/tmp/bot.deltas'

    def __init__(self):
        pass

    @property
    def is_proxy(self):
        if self.proxy:
            return True
        return False

    def tokenized_request(
            self,
            url,
            data=None,
            method='GET',
            headers=None,
            pages=None,
            paginate=True,
            pagecount=0
        ):

        logger.info('(F) %s' % url)
        _headers = {}
        if self.TOKEN:
            _headers['Authorization'] = 'token %s' % self.TOKEN

        # reactions
        accepts = [
            u'application/json',
            u'application/vnd.github.mockingbird-preview',
            u'application/vnd.github.sailor-v-preview+json',
            u'application/vnd.github.starfox-preview+json',
            u'application/vnd.github.v3+json',
            u'application/vnd.github.squirrel-girl-preview+json'
        ]
        _headers['Accept'] = ','.join(accepts)
        if headers is not None:
            for k, v in headers.items():
                _headers[k] = v


        if method == 'GET':
            rr = requests.get(url, headers=_headers)
        elif method == 'POST':
            rr = requests.post(url, data=data, headers=_headers)

        if rr.headers.get('Status') == '204 No Content':
            data = None
        else:
            try:
                data = rr.json()
            except json.decoder.JSONDecodeError as e:
                logger.error(e)
                import epdb; epdb.st()

        rheaders = dict(rr.headers)

        if not paginate:
            return (rheaders, data)

        # exit early if enough pages were collected
        pagecount += 1
        if pages and pagecount >= pages:
            return (rheaders, data)

        if 'Link' in rheaders:
            links = self.extract_header_links(rheaders)
            if links.get('next'):
                (_headers, _data) = self.tokenized_request(links['next'], pagecount=pagecount)
                data += _data

        return (rheaders, data)

    # CACHED PROXY
    def cached_tokenized_request(
            self,
            url,
            data=None,
            method='GET',
            headers=None,
            pages=None,
            pagecount=0,
            context='api.github.com'
        ):

        '''fetch a raw github api url, cache the result, munge it and send it back'''

        path = url.replace('https://%s/' % context, '')
        path = path.split('/')
        if path[-1] != 'graphql':
            dtype = path[-1]
            path = '/'.join(path[:-1])
            fixdir = os.path.join(self.fixturedir, context, path)
        else:
            fixdir = os.path.join(self.fixturedir, context, 'graphql')
            m = hashlib.md5()
            m.update(data)
            dtype = m.hexdigest()

        loaded = False
        if self.usecache:
            try:
                rheaders, rdata = self.read_fixture(fixdir, dtype)
                loaded = True
            except RequestNotCachedException:
                pass

        # add new data locally
        if method in ['POST', 'UPDATE', 'DELETE'] and  path[-1] != 'graphql':
            jdata = data
            try:
                jdata = json.loads(data)
            except json.decoder.JSONDecodeError:
                pass
            self.handle_change(context, url, headers, data, method=method)
            #import epdb; epdb.st()
            return {}, {}

        if not loaded and method == 'GET' and not self.is_proxy:
            # issues without labels won't have a labels file, so we have to return empty data

            # get the issue data for verification
            if url.endswith('/labels'):
                iheaders, idata = self.get_cached_issue_data(url=url)
                if not idata['labels']:
                    return {}, []
            else:
                print('HUH?')
                import epdb; epdb.st()

        # merge in the deltas
        #if loaded and not self.is_proxy and method == 'GET':
        #    rdata = self.get_changes(context, url, rdata)
        if self.usecache:
            rdata = self.get_changes(context, url, rdata)

        if not loaded and self.is_proxy:
            rheaders, rdata = self.tokenized_request(
                url,
                data=data,
                method=method,
                headers=headers,
                pages=pages,
                pagecount=pagecount,
                paginate=False
            )

            if not os.path.exists(fixdir):
                os.makedirs(fixdir)
            self.write_fixture(fixdir, dtype, rdata, rheaders, compress=True)
            loaded = True

        if not loaded:

            raise Exception(
                '%s was not cached and the server is not in proxy mode' % url
            )

        new_headers = self.replace_data_urls(rheaders)
        new_data = self.replace_data_urls(rdata)
        return new_headers, new_data


    def get_cached_issue_data(self, namespace=None, repo=None, number=None, url=None):
        # https://api.github.com/repos/ansible/ansible/issues/55062/labels
        urlparts = url.split('/')
        numix = None
        for idx, urlpart in enumerate(urlparts):
            if urlpart.isdigit():
                numix = idx
                break
        diskpath = urlparts[2:numix]
        fixdir = os.path.join(self.fixturedir, '/'.join(diskpath))
        (headers, data) = self.read_fixture(fixdir, urlparts[numix])
        return (headers, data)

    def get_changes(self, context, url, data):
        path = url.replace('https://%s/' % context, '')
        path = path.split('/')


        if not 'issues' in path and not 'issue' in path and not 'pull' in path and not 'pulls' in path:
            return data

        numix = None
        for idx, _path in enumerate(path):
            if _path.isdigit():
                numix = idx
                break

        if numix is None:
            import epdb; epdb.st()

        inumber = path[numix]

        dtype = path[-1]
        _path = '/'.join(path[:numix+1])
        fixdir = os.path.join(self.deltadir, context, _path)
        if not os.path.exists(fixdir):
            return data

        efile = os.path.join(fixdir, 'events.json')
        if not os.path.exists(efile):
            return data

        with open(efile, 'r') as f:
            events = json.loads(f.read())

        dtype = None
        if url.endswith(inumber):
            dtype = 'issue'
        elif url.endswith('events'):
            dtype = 'events'
        elif url.endswith('comments'):
            dtype = 'comments'

        for event in events:
            if dtype == 'events':
                data.append(event)
                continue
            if dtype == 'comments' and event['event'] == 'commented':
                data.append(event)
                continue
            if dtype == 'comments' and event['event'] != 'commented':
                continue
            if dtype == 'issue':
                data['updated_at'] = event['created_at']
                if event['event'] == 'labeled':
                    found = False
                    for label in data['labels']:
                        if label['name'] == event['label']['name']:
                            found = True
                            break
                    if not found:
                        data['labels'].append({'name': event['label']['name']})
                elif event['event'] == 'unlabeled':
                    found = False
                    for label in data['labels']:
                        if label['name'] == event['label']['name']:
                            found = label
                            break
                    if found:
                        data['labels'].remove(found)
                elif event['event'] == 'commented':
                    data['comments'] += 1
                #else:
                #    import epdb; epdb.st()

                continue

            #import epdb; epdb.st()

        #import epdb; epdb.st()
        return data

    def handle_change(self, context, url, headers, data, method=None):

        # GET POST UPDATE DELETE

        path = url.replace('https://%s/' % context, '')
        path = path.split('/')

        jdata = None
        try:
            jdata = json.loads(data)
        except Exception:
            pass

        if method.lower() == 'delete':
            if path[-2] == 'labels':
                jdata = [path[-1]]
                path = path[:-1]
            else:
                import epdb; epdb.st()

        dtype = path[-1]
        _path = '/'.join(path[:-1])
        fixdir = os.path.join(self.deltadir, context, _path)
        if not os.path.exists(fixdir):
            os.makedirs(fixdir)

        #fixfile = os.path.join(fixdir, '%s.json' % path[-1])
        efile = os.path.join(fixdir, 'events.json')

        #ldata = []
        #if os.path.exists(fixfile):
        #    with open(fixfile, 'r') as f:
        #        ldata = json.loads(f.read())

        edata = []
        if os.path.exists(efile):
            with open(efile, 'r') as f:
                edata = json.loads(f.read())

        if path[-1] == 'labels':
            #jdata = json.loads(data)

            if isinstance(jdata, dict) and 'labels' in jdata:
                labels = jdata['labels']
            else:
                labels = jdata[:]
            for label in labels:
                thisevent = self.get_new_event()
                thisevent['actor']['login'] = 'ansibot'
                thisevent['actor']['url'] = 'https://api.github.com/users/ansibot'
                thisevent['user']['login'] = 'ansibot'
                thisevent['user']['url'] = 'https://api.github.com/users/ansibot'
                if method.lower() == 'post':
                    thisevent['event'] = 'labeled'
                elif method.lower() == 'delete':
                    thisevent['event'] = 'unlabeled'
                thisevent['label'] = {'name': label}
                edata.append(thisevent)

        elif path[-1] == 'comments':
            #jdata = json.loads(data)
            thisevent = self.get_new_event()
            thisevent['actor']['login'] = 'ansibot'
            thisevent['actor']['url'] = 'https://api.github.com/users/ansibot'
            thisevent['user']['login'] = 'ansibot'
            thisevent['user']['url'] = 'https://api.github.com/users/ansibot'
            thisevent['event'] = 'commented'
            thisevent['body'] = jdata['body'] 
            edata.append(thisevent)

        else:
            import epdb; epdb.st()

        with open(efile, 'w') as f:
            f.write(json.dumps(edata, indent=2))


    def get_new_event(self):
        thisevent = {
            'id': None,
            'node_id': None,
            'url': None,
            'actor': {
                'login': None,
                'url': None,
            },
            'user': {
                'login': None,
                'url': None
            },
            'event': None,
            'commit_id': None,
            'commit_url': None,
            'created_at': datetime.datetime.now().isoformat(),
        }
        return thisevent

    def extract_header_links(self, headers):

        links = {}
        for line in headers['Link'].split(','):
            parts = line.split(';')
            rel = parts[-1].split('"')[1]
            link = parts[0].replace('<', '').replace('>', '').strip()
            links[rel] = link

        #import epdb; epdb.st()
        return links

    def fetch_first_issue_number(self, org, repo):
        iurl = 'https://api.github.com/repos/%s/%s/issues' % (org, repo)
        (issues_headers, issues) = self.tokenized_request(iurl, pages=1) 
        return issues[0]['number']


    def get_issue_fixture(self, org, repo, number, ftype=None):
        '''Read the fixture(s) from disk and send them back'''
        logger.info('load %s %s %s' % (org, repo, number))
        number = int(number)
        bd = os.path.join(self.fixturedir, 'repos', org, repo, str(number))
        fns = sorted(glob.glob('%s/*' % bd))
        fns = [x for x in fns if ftype in os.path.basename(x)]

        result = None
        headers = None

        for fn in fns:
            if fn.endswith('.gz'):
                data = read_gzip_json(fn)
            else:
                with open(fn, 'r') as f:
                    try:
                        data = json.loads(f.read())
                    except ValueError as e:
                        logger.error('unable to parse %s' % fn)
                        raise Exception(e)

            data = self.replace_data_urls(data)
            if '.headers' in fn:
                headers = data.copy()
            else:
                result = data.copy()

        return headers, result


    def replace_data_urls(self, data):
        '''Point ALL urls back to this instance instead of the origin'''
        data = json.dumps(data)
        data = data.replace('https://api.github.com', BASEURL)
        data = data.replace('https://github.com', BASEURL)
        data = data.replace('https://api.shippable.com', BASEURL)
        data = data.replace('https://app.shippable.com', BASEURL)
        data = json.loads(data)
        return data

    def read_fixture(self, directory, fixture_type):

        hfn = os.path.join(directory, '%s.headers.json' % fixture_type)
        if not os.path.exists(hfn):
            hfn += '.gz'
            if not os.path.exists(hfn):
                raise RequestNotCachedException
            logger.debug('read %s' % hfn)
            headers = read_gzip_json(hfn)
        else:
            logger.debug('read %s' % hfn)
            with open(hfn, 'r') as f:
                headers = json.load(f.read())

        dfn = os.path.join(directory, '%s.json' % fixture_type)
        if not os.path.exists(dfn):
            dfn += '.gz'
            if not os.path.exists(dfn):
                raise RequestNotCachedException
            logger.debug('read %s' % dfn)
            data = read_gzip_json(dfn)
        else:
            logger.debug('read %s' % dfn)
            with open(dfn, 'r') as f:
                data = json.load(f.read())

        return headers, data

    def write_fixture(self, directory, fixture_type, data, headers, compress=False):

        if not os.path.exists(directory):
            os.makedirs(directory)

        if compress:
            hfn = os.path.join(directory, '%s.headers.json.gz' % fixture_type)
            write_gzip_json(hfn, headers)
            dfn = os.path.join(directory, '%s.json.gz' % fixture_type)
            write_gzip_json(dfn, data)
        else:
            with open(os.path.join(directory, '%s.json' % fixture_type), 'w') as f:
                f.write(json.dumps(data, indent=2, sort_keys=True))
            with open(os.path.join(directory, '%s.headers.json' % fixture_type), 'w') as f:
                f.write(json.dumps(headers, indent=2, sort_keys=True))
