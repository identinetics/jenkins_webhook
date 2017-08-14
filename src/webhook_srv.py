#!/usr/bin/env python3

import argparse
import datetime
import hashlib
import json
import os
import sys
import time
import traceback
import werkzeug.serving
from werkzeug.wrappers import BaseRequest, BaseResponse

class InvalidCommitmessage(Exception):
    pass

class NotACommitMessage(Exception):
    pass

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
        reqpath = req.path.rstrip('/')
        getpath = self.args.getpath.rstrip('/')
        postpath = self.args.postpath.rstrip('/')
        if req.method == 'GET' and reqpath == getpath:
            resp = self.get_handler(req)
        elif req.method == 'POST' and reqpath == postpath:
                resp = self.post_handler(req)
        else:
            resp = BaseResponse('Invalid path (%s) or HTTP method (%s) not supported' % (req.path, req.method),
                                mimetype='text/plain')
            if self.args.verbose: print('{}: reqpath: {}; postpath: {}'.format(req.method, reqpath, postpath))
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
        print('*' * 20, file=sys.stderr)
        print(post_data, file=sys.stderr)
        print('*' * 20, file=sys.stderr)
        try:
            result = self.save_commit_message(post_data)
        except InvalidCommitmessage:
            response = BaseResponse('Invalid requst format or repo owner not authorized', mimetype='text/plain')
            response.status_code = 403
            return response
        except NotACommitMessage:
            response = BaseResponse('Message ignored: not a github commit message', mimetype='text/plain')
            response.status_code = 200
            return response

        self.update_aggregate()
        response_contents = '["OK"]'
        return BaseResponse(response_contents,
                            mimetype='application/json',
                            direct_passthrough=False)

    def save_commit_message(self, post_data) -> str:
        try:
            commit_message = json.loads(post_data)
        except json.decoder.JSONDecodeError as e:
            self.print_error_with_data('JSON decode error', post_data, e)
            raise InvalidCommitmessage
        (repoowner, reponame, branch) = self.get_repo_and_branch(commit_message)
        try:
            _ = commit_message['head_commit']
        except KeyError:
            raise NotACommitMessage
        if repoowner in self.authz_owners:
            filedir = os.path.join(self.args.datadir, repoowner, reponame)
            filepath = os.path.join(filedir, branch + '.json')
            os.makedirs(filedir, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as fd:
                fd.write(post_data)
        else:
            print('Repo owner %s not authorized' % repoowner, file=sys.stderr)
            raise InvalidCommitmessage

    def get_repo_and_branch(self, commit_message) -> tuple:
        try:
            (repoowner, reponame) = commit_message['repository']['full_name'].split('/')
        except KeyError as e:
            try:
                repoowner = commit_message['repository']['owner']['name']
            except KeyError as e:
                self.print_error_with_data("Missing key ['repository']['owner']['name']", commit_message, e)
                raise
            try:
                reponame = commit_message['repository']['name']
            except KeyError as e:
                self.print_error_with_data("Missing key ['repository']['name']", commit_message, e)
                raise
        try:
            branch = commit_message['ref'].split('/')[-1]
        except KeyError:
            branch = commit_message['repository']['default_branch']
        return (repoowner, reponame, branch)


    def print_error_with_data(self, msg, post_data, e):
        print(msg, file=sys.stderr)
        print('=' * 20, file=sys.stderr)
        print(post_data, file=sys.stderr)
        print('=' * 20, file=sys.stderr)
        print(e.args[0], file=sys.stderr)
        traceback.print_exc()

    #def is_commit_msg(self, cm):
    #    return True

    def update_aggregate(self):
        counter = 0
        try:
            for cmf in self.get_commit_messages_files():
                cm = json.load(open(cmf, encoding='utf-8'))
                (repoowner, reponame, branch) = self.get_repo_and_branch(cm)
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
        except Exception as e:
            self.print_error_with_data('Error when updating aggregate', cm, e)


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
