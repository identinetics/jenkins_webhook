'''
poll commit messages on webhook proxy and trigger jenkins builds if there is a new message
'''

#!/usr/bin/python3

import argparse
import calendar
import csv
import json
import logging
import os
import re
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
import time

import jenkins

def main():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    tj = TriggerJenkins()
    tj.get_args()
    tj.read_config()
    tj.connect_jenkins()
    tj.poll_and_trigger()


class TriggerJenkins:
    def __init__(self):
        self.COMMENTKEY = "#Jenkins Webhook"
        FORMAT = '%(asctime)-15s %(message)s'
        logging.basicConfig(format=FORMAT)

    def get_args(self):
        self.parser = argparse.ArgumentParser(
            description='Trigger jenkins builds with webhook proxy polling')
        default_datadir = os.path.join(os.path.expanduser("~"), 'jenkins-webhook/data')
        default_configfile = os.path.join(default_datadir, '.config.json')
        self.parser.add_argument('-c', '--config', type=argparse.FileType('r'),
                                 required=True, default=default_configfile)
        self.parser.add_argument('-D', '--datadir', default=default_datadir,
                                 help='Directory to store status page')
        self.parser.add_argument('-j', '--jenkins-baseurl', dest='jenkins_baseurl',
                                 default='http://localhost:8080/buildByToken/build',
                                 help='Jenkins build trigger path')
        self.parser.add_argument('-N', '--nosslcertverify', action='store_true')
        self.parser.add_argument('-p', '--password', required=True,
                                 help='Use API-Token from user settings as password')
        self.parser.add_argument('-t', '--jenkins-apitoken', dest='jenkins_apitoken')
        self.parser.add_argument('-u', '--user', required=True)
        self.parser.add_argument('-v', '--verbose', action='store_true')
        self.parser.add_argument('-w', '--webhook-proxy', dest='webhook_proxy',
                                 default='http://localhost:8081/status',
                                 help='Webhook proxy status page URL')
        self.args = self.parser.parse_args()
        if self.args.verbose:
            logger = logging.getLogger()
            logger.setLevel(logging.DEBUG)
        logging.debug('datadir:' + self.args.datadir)
        logging.debug('jenkins-baseurl:' + self.args.jenkins_baseurl)
        logging.debug('jenkins-apitoken:' + (self.args.jenkins_apitoken or ''))
        logging.debug('webhook-proxy:' + self.args.webhook_proxy)
        self.args.sslcert_verify = False if self.args.nosslcertverify else True


    def read_config(self):
        with self.args.config as fd:
            self.gh2jenkins_map = {}
            for line in fd.readlines():
                if line.startswith('#') or re.search('^s*$', line):
                    continue
                (k, v) = line.split()
                self.gh2jenkins_map[k] = v
                logging.debug('config:' + line.rstrip())
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

    def connect_jenkins(self):
        logging.debug('connecting to %s as %s' % (self.args.jenkins_baseurl, self.args.user))
        self.server = jenkins.Jenkins(self.args.jenkins_baseurl,
                                 username=self.args.user,
                                 password=self.args.password)
        job_list = self.server.get_jobs()
        logging.debug('found {} jobs'.format(len(job_list)))
        self.job_set = set()
        for j in job_list:
            self.job_set.add(j['name'])

    def poll_and_trigger(self):
        previous_status_file = os.path.join(self.args.datadir, '.status_previous.json')
        try:
            status_prev = json.load(open(previous_status_file))
            logging.debug('previous status:' + str(status_prev))
        except:
            status_prev = {}
            logging.debug('no previous status found')
        status_current = self.get_commit_messages()
        if status_current == status_prev:
            logging.debug('nothing new')
        else:
            for k in status_current:
                if k != self.COMMENTKEY:
                    logging.debug('reading commit message: ' + k + str(status_current[k]))
                    #jenkins_url_template = '{}/job/%s/build?token={}'.format(
                    #    self.args.jenkins_baseurl,
                    #    self.args.jenkins_apitoken)
                    self.trigger_jenkins_if_new_or_changed(k, status_current, status_prev)
            with open(previous_status_file, 'w', encoding='utf-8') as fd:
                fd.write(json.dumps(status_current, indent=4))

    def get_commit_messages(self):
        response = requests.get(self.args.webhook_proxy, verify=self.args.sslcert_verify)
        logging.debug(self.args.webhook_proxy + ' HTTP ' + str(response.status_code))
        if response.status_code >= 400:
            msg = 'Request to %s failed: %s' % (self.args.webhook_proxy, response.text)
            logging.error(msg)
            raise Exception(msg)
        else:
            cm = json.loads(response.text)
            return cm

    def trigger_jenkins_if_new_or_changed(self, branchpath, status_current, status_prev, url_template=None):
        # Jobs can be triggered via API (not for multibranch pipelines), CLI, API/buildbytoken-Plugin
        # Web-URL (requires to pass crumb) or python-jenkins API. This version uses the py API.
        if branchpath in status_prev:
            if status_current[branchpath] == status_prev[branchpath]:
                logging.debug('no change found for ' + branchpath)
                return
        try:
            jenkins_job = self.gh2jenkins_map[branchpath]
            if jenkins_job not in self.job_set:
                logging.error('Job %s not found in Jenkins' % jenkins_job)
                raise KeyError
            #jenkins_trigger_url = url_template % jenkins_job
            #logging.info('triggering Jenkins build for {} at {}'.format(branchpath, jenkins_trigger_url))
            #response = requests.get(jenkins_trigger_url, auth=(self.args.user, self.args.password)) API version
            if self.args.jenkins_apitoken:
                self.server.build_job(jenkins_job, token=self.args.jenkins_apitoken)
            else:
                self.server.build_job(jenkins_job)
            logging.info('triggering build for ' + branchpath)
        except KeyError:
            logging.error('No config entry for %s' % branchpath)


if __name__ == '__main__':
    main()
