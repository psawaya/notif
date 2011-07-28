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
#  Shane da Silva <sdasilva@mozilla.com>
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

import json
import logging

from validate import NotificationValidator
from services.util import convert_config
from webob.dec import wsgify
from webob.exc import HTTPAccepted, HTTPBadRequest

from notifserver.storage import get_message_backend


logger = logging.getLogger('postoffice')


class PostOffice(object):
    """Forwards messages on behalf of web apps.

    The POST Office (named so due to the fact that it only accepts POST
    requests) simply takes messages and forwards them to the message
    broker for routing.

    If run in a development environment, the POST Office can perform
    validation of incoming messages itself. For production environments
    however, this does not scale, so it simply dumps any messages into
    a queue in the broker which are validated and routed to their
    destination by another worker.
    
    """

    def __init__(self, config, validator=None):
        """Initialize the server."""
        self.msg_backend = get_message_backend(config)
        self.msg_queue_name = config['notifs_queue_name']

        self.validator = validator 
       
    @wsgify
    def __call__(self, request):
        # Reject any non-POST requests
        if request.method != 'POST':
            logger.error("Ignoring %s request", request.method)
            raise HTTPBadRequest("'%s' requests not allowed" % request.method)

        logger.info("Message received: %s", request.body)
    
        if self.validator:
            # If we're validating ourselves route message directly 
            print 'route_message'
            return self.route_message(request)
        else:
            print 'forward_message'
            # Otherwise forward message to be validated later
            return self.forward_message(request)

    def route_message(self, request):
        """Validates and routes message to recipient."""
        msg = json.loads(request.body)
        body = json.loads(msg['body'])

        self.validator.validate(msg, body)

        try:
            self.msg_backend.publish_message(json.dumps(msg), body['token'])
            return HTTPAccepted()
        except:
            logger.error("Error publishing message with token '%s'" % body['token'])
            raise

    def forward_message(self, request):
        """Queues messages in the message broker to be validated at a later time."""
        try:
            self.msg_backend.queue_message(request, self.msg_queue_name)
            return HTTPAccepted()
        except:
            logger.error("Error queueing message in message broker")
            raise


def make_post_office(global_config, **local_config):
    """Creates a POST Office that simply queues messages in the broker.
    
    This is a factory function for integration with Paste.
    """
    config = global_config.copy()
    config.update(local_config)
    params = convert_config(config)
    return PostOffice(params)


def make_post_office_router(global_config, **local_config):
    """Creates a POST Office that validates and routes messages.

    This is useful for development environments where running
    a separate validation/routing server is inconvenient.

    This is a factory function for integration with Paste.
    """
    config = global_config.copy()
    config.update(local_config)
    params = convert_config(config)
    return PostOffice(params, NotificationValidator())

