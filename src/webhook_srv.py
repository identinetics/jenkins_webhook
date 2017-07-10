#!/usr/bin/env python3
#-*- coding:utf-8 -*-


import json
import sys
import time
import werkzeug.serving
from werkzeug.wrappers import BaseRequest, BaseResponse


HOST_NAME = '0.0.0.0'
PORT_NUMBER = 8080


def handle_hook(payload):
    with open('/tmp/pushmsg.json', 'w') as fd:
        fd.write(payload)


class AppHandler():
    def get_handler(self, req):
        json = '[{"key": "val"}]'
        return BaseResponse(json,
                            mimetype='application/json',
                            direct_passthrough=False)

    def post_handler(self, req):
        # Check that the IP is within the Github ranges (if not here, then in proxy)
        #if not any(req.headers.environ['REMOTE_ADDR'][0].startswith(IP)
        #           for IP in ('192.30.252', '192.30.253', '192.30.254', '192.30.255')):
        #    s.send_error(403)

        if req.path.startswith('/github'):
            length = int(req.headers.environ['CONTENT_LENGTH'])
            post_data = req.data.decode(req.charset)
            #payload = json.loads(post_data['payload'][0])

            handle_hook(post_data)
            json = '["OK"]'
            return BaseResponse(json,
                                mimetype='application/json',
                                direct_passthrough=False)
        else:
            response = BaseResponse('Path not found', mimetype='text/plain')
            response.status_code = 404
            return response


    def wsgi_application(self, environ, start_response):
        req = BaseRequest(environ)
        if req.method == 'POST':
            resp = self.post_handler(req)
        elif req.method == 'GET':
            resp = self.get_handler(req)
        else:
            response = BaseResponse('HTTP method not supported', mimetype='text/plain')
            response.status_code = 400
            return response
        return resp(environ, start_response)


if __name__ == '__main__':
    app_handler = AppHandler()
    print(time.asctime(), "Server starting %s:%s" % (HOST_NAME, PORT_NUMBER))
    try:
        werkzeug.serving.run_simple(
            HOST_NAME,
            PORT_NUMBER,
            app_handler.wsgi_application,
            use_debugger=True)
    except KeyboardInterrupt:
        pass
    print(time.asctime(), "Server terminating %s:%s" % (HOST_NAME, PORT_NUMBER))
