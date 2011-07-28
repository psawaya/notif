# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is the Mozilla Push Notifications Server. 
#
# The Initial Developer of the Original Code is
# Mozilla Corporation.
# Portions created by the Initial Developer are Copyright (C) 2011
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#  Paul Sawaya <me@paulsawaya.com>
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

from services.config import Config

from stormed import Connection, Message
from tornado.ioloop import IOLoop
import tornado.web

class SSEServer(object):
    def __init__(self, config):
        self.config = config
        self.conn = None
        
        self.makeAMQPConnection()
        
        self.webapp = self.makeWebFrontend()
        self.webapp.listen(8888)
        
        io_loop = IOLoop.instance()
        print ' [*] Waiting for messages. To exit press CTRL+C'
        try:
            io_loop.start()
        except KeyboardInterrupt:
            self.conn.close(io_loop.stop)

    def makeAMQPConnection(self, token='', callback=None):
        def notifsCallback(msg):
            if callback:
                callback(msg)
            print " [x] Received %r \n \n for token %s" % (msg.body, token)
                
        def on_connect():
            print "on_connect"
            ch = self.conn.channel()
            ch.queue_declare(queue=token, durable=True, exclusive=False, auto_delete=False)
            ch.consume(token, notifsCallback, no_ack=True)
            ch.qos(prefetch_count=1)
        
        self.conn = Connection(host=self.config['broker_host'],port=self.config['broker_amqp_port'])
        self.conn.connect(on_connect)
        
    def makeWebFrontend(self):
        
        thisSSE = self
        
        class NotificationsWebHandler(tornado.web.RequestHandler):
            @tornado.web.asynchronous
            def get(self, token):
                self.set_header("Content-Type","text/event-stream")        
                self.set_header("Cache-Control","no-cache")        
                self.set_header("Connection","keep-alive")

                self.notifID = 0

                self.flush()
                
                def callbackFunc(msg):
                    self.publishNotification(msg.body)

                thisSSE.makeAMQPConnection(token, callbackFunc)

            def publishNotification(self, notifData):
                self.write("id: %i\n" % self.notifID)
                self.write("data:")
                self.write(notifData)

                self.notifID+=1
        
        routes = [
            (r"/feed/(.*)", NotificationsWebHandler)
        ]
        
        return tornado.web.Application(routes)

def make_sse_server(config_filename):
    configItems = ['configuration', 'broker_host', 'broker_amqp_port', 'broker_username', 'broker_password', 'broker_virtual_host', 'incoming_exchange_name', 'notifs_queue_name']
    SSEConfig = Config(config_filename)
    configMap = dict([(item, SSEConfig.get("app:post_office", item)) for item in configItems])
    
    return SSEServer(configMap)

if __name__ == "__main__":
    SSE = make_sse_server("../development.ini")
