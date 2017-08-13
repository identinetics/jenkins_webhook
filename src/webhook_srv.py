#!/usr/bin/env python3

import argparse
import datetime
import json
import os
import sys
import time
import werkzeug.serving
from werkzeug.wrappers import BaseRequest, BaseResponse


def main():
    invocation = Invocation()
    if True or invocation.args.verbose:
        print(now_iso8601(), "Server starting %s:%s" % (invocation.args.hostname, invocation.args.port))
        print('getpath: %s' % invocation.args.getpath.strip('/'))
        print('postpath: %s' % invocation.args.postpath.strip('/'))
        print('ownerlist: %s' % invocation.args.ownerlist)
        print('datadir: %s' % invocation.args.datadir)
    app_handler = AppHandler(invocation.args)
    try:
        werkzeug.serving.run_simple(
            invocation.args.hostname,
            invocation.args.port,
            app_handler.wsgi_application,
            use_debugger=True)
    except KeyboardInterrupt:
        pass
    print(now_iso8601(), "Server terminating %s:%s" % (invocation.args.hostname, invocation.args.port))


def now_iso8601():
    return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


class Invocation:
    def __init__(self, testargs=None):
        self.parser = argparse.ArgumentParser(description='github webhook proxy')
        self.parser.add_argument('-H', '--hostname', dest='hostname', default='0.0.0.0',
                                 help='Service host/IP')
        self.parser.add_argument('-p', '--port', dest='port', type=int, default=8081, help='Service')
        self.parser.add_argument('-d', '--debug', action='store_true', help='activate Werkzeug debug')
        default_datadir = os.path.join(os.path.expanduser("~"), 'jenkins-webhook/data')
        self.parser.add_argument('-D', '--datadir', dest='datadir', default=default_datadir,
                                 help='Directory to store webhook payloads')
        self.parser.add_argument('-o', '--ownerlist', dest='ownerlist', default='', required=True,
                                 help='List of authorized github repo owners, separated with commas, no whitespace')
        self.parser.add_argument('-G', '--getpath', dest='getpath', default='/status',
                                 help='API path for GET operations')
        self.parser.add_argument('-P', '--postpath', dest='postpath', default='/github',
                                 help='API path for POST operations')
        self.parser.add_argument('-v', '--verbose', action='store_true')

        self.args = self.parser.parse_args()


class AppHandler():
    def __init__(self, args):
        self.args = args
        os.makedirs(self.args.datadir, exist_ok=True)
        self.authz_owners = set(self.args.ownerlist.split(','))
        self.aggregate_path = os.path.join(self.args.datadir, '.status.json')
        self.COMMENTKEY = "#Jenkins Webhook"
        try:
            self.all_commits = json.load(open(self.aggregate_path, 'r', encoding='utf-8'))
        except:
                self.all_commits = {
                self.COMMENTKEY: {
                    "status": "no commit message available",
                    "timestamp": now_iso8601(),
                }
            }

    def wsgi_application(self, environ, start_response):
        req = BaseRequest(environ)
        if req.method == 'GET' and req.path.strip('/') == self.args.getpath:
            resp = self.get_handler(req)
        elif req.method == 'POST' and req.path.strip('/') == self.args.postpath:
            resp = self.post_handler(req)
        else:
            resp = BaseResponse('Invalid path (%s) or HTTP method (%s) not supported' % (req.path, req.method),
                                mimetype='text/plain')
            resp.status_code = 400
        return resp(environ, start_response)

    def get_handler(self, req):
        response_contents = json.dumps(self.all_commits, indent=4)
        return BaseResponse(response_contents,
                            mimetype='application/json',
                            direct_passthrough=False)

    def post_handler(self, req):
        length = int(req.headers.environ['CONTENT_LENGTH'])
        post_data = req.data.decode(req.charset)
        result = self.save_commit_message(post_data)
        if result == 'OK':
            self.update_aggregate()
            response_contents = '["OK"]'
            return BaseResponse(response_contents,
                                mimetype='application/json',
                                direct_passthrough=False)
        else:
            response = BaseResponse('Invalid requst format or repo owner not authorized', mimetype='text/plain')
            response.status_code = 403
            return response

    def print_error_with_postdata(self, msg, post_data, e):
        print(msg, file=sys.stderr)
        print('=' * 20, file=sys.stderr)
        print(post_data, file=sys.stderr)
        print('=' * 20, file=sys.stderr)
        print(e.args[0], file=sys.stderr)

    def save_commit_message(self, post_data) -> str:
        try:
            commit_message = json.loads(post_data)
        except json.decoder.JSONDecodeError as e:
            self.print_error_with_postdata('JSON decode error', post_data, e)
            return 'NOK'
        try:
            repoowner = commit_message['repository']['owner']['name']
        except:
            self.print_error_with_postdata("Missing key ['repository']['owner']['name']", post_data, e)
            return 'NOK'
        try:
            reponame = commit_message['repository']['name']
        except:
            self.print_error_with_postdata("Missing key ['repository']['name']", post_data, e)
        if repoowner in self.authz_owners:
            branch = commit_message['ref'].split('/')[-1] + '.json'
            filedir = os.path.join(self.args.datadir, repoowner, reponame)
            filepath = os.path.join(filedir, branch)
            os.makedirs(filedir, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as fd:
                fd.write(post_data)
            return 'OK'
        else:
            print('Repo owner %s not authorized' % repoowner, file=sys.stderr)
            return 'NOK'

    def update_aggregate(self):
        counter = 0
        for cmf in self.get_commit_messages_files():
            cm = json.load(open(cmf, encoding='utf-8'))
            repoowner = cm['repository']['owner']['name']
            reponame = cm['repository']['name']
            branch = cm['ref'].split('/')[-1]
            commit_id = cm['head_commit']['id']
            commit_msg = cm['head_commit']['message']
            commit_ts = cm['head_commit']['timestamp']
            branchpath = repoowner + '/' + reponame + '/' + branch
            commit_data = {'commit_id': commit_id,
                           'commit_msg': commit_msg,
                           'commit_ts': commit_ts}
            self.all_commits[branchpath] = commit_data
            counter += 1
        self.all_commits[self.COMMENTKEY] = {
                "status": "%d commit messages available" % counter,
                "timestamp": now_iso8601()}
        json.dump(self.all_commits, open(self.aggregate_path, 'w', encoding='utf-8'), indent=4)


    def get_commit_messages_files(self) -> set:
        if self.args.verbose: print('searching for *.json in ' + self.args.datadir)
        cm_files = set()
        for (path, dirs, files) in os.walk(self.args.datadir):
            for (path, dirs, files) in os.walk(self.args.datadir):
                for f in files:
                    if f.endswith('.json') and not f.startswith('.'):
                        cm_filepath = os.path.join(path, f)
                        cm_files.add(cm_filepath)
        return cm_files


if __name__ == '__main__':
    main()
