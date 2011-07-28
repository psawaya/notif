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

import base64
import httplib
import json
import random
import urllib

import pika
from pika.adapters import BlockingConnection

from notifserver.storage import logger


class RabbitMQStorage(object):
    """Manages message storage with a RabbitMQ server."""

    def __init__(self, **config):
        self.broker_user = config['username']
        self.broker_pass = config['password']
        self.broker_host = config['host']
        self.broker_amqp_port = int(config['amqp_port'])
        self.broker_http_port = int(config['http_port'])
        self.broker_vhost = config['virtual_host']
        self.incoming_exchange_name = config['incoming_exchange_name']
        self.routing_queue_name = config['routing_queue_name']

        logger.info("Message Broker User: %s" % self.broker_user)
        logger.info("Message Broker Host: %s" % self.broker_host)
        logger.info("Message Broker Port: %s" % self.broker_amqp_port)
        logger.info("Message Broker Virtual Host: %s" % self.broker_vhost)

        # Create connection parameters object for easy reuse
        self.conn_params = pika.ConnectionParameters(
            credentials=pika.PlainCredentials(
                self.broker_user,
                self.broker_pass,
            ),
            host=self.broker_host,
            port=self.broker_amqp_port,
            virtual_host=self.broker_vhost,
        )

        # Create HTTP connection object for easy reuse
        self.http_conn = httplib.HTTPConnection(self.broker_host, self.broker_http_port)

    @classmethod
    def get_name(cls):
        return 'rabbitmq'
    
    def _get_amqp_conn(self):
        return BlockingConnection(self.conn_params)  

    def _get_http_conn(self):
        return self.http_conn

    def create_client_queue(self, username):
        user_exchange_name = username

        # Create a unique client id to also be used as the name of the queue
        client_queue_name = "%x" % random.getrandbits(256)

        logger.info("Creating queue %s for user %s", client_queue_name, username)

        # Create the user exchange (if it doesn't already exist) and a client
        # queue with the generated name.
        conn = self._get_amqp_conn()
        try:
            channel = conn.channel()

            logger.debug("Declaring exchange %s", user_exchange_name)
            channel.exchange_declare(
                exchange=user_exchange_name,
                durable=True,
                type='fanout',
            )

            logger.debug("Declaring queue %s", client_queue_name)
            channel.queue_declare(queue=client_queue_name, durable=True)

            logger.debug("Binding queue %s to exchange %s",
                client_queue_name,
                user_exchange_name,
            )
            channel.queue_bind(
                exchange=user_exchange_name,
                queue=client_queue_name,
            )
        except:
            logger.error("Error creating new client queue")
            raise
        finally:
            logger.debug("Closing AMQP connection to broker")
            conn.disconnect()

        return {
            'queue_id': client_queue_name,
            'host': self.broker_host,
            'port': self.broker_amqp_port,
        }
   
    def create_subscription(self, username, token):
        user_exchange_name = username

        # TODO: See if we can remove this call entirely
        self._ensure_exchanges_exist(self.incoming_exchange_name, user_exchange_name)
       
        self._add_binding(
            self.incoming_exchange_name,
            user_exchange_name,
            token,
        )

    def _add_binding(self, source_exch, dest_exch, routing_key):
        # XXX: OH EM GEE this is a hack. Creating Exchange-to-exchange (E2E)
        # bindings is a RabbitMQ-specific extension, so the pika AMQP
        # client doesn't support it. The RabbitMQ REST API does however,
        # so we do a quick HTTP POST here to create the binding.
        #
        # To do this properly, we'll probably have to roll our own version
        # of Pika which supports the exchange.bind method call.
        http_conn = self._get_http_conn()
        try:
            auth_headers = {
                'Authorization': 'Basic ' +
                    base64.b64encode('%s:%s' % \
                        (self.broker_user, self.broker_pass)
                    ),
                'Content-Type': 'application/json',
            }
            
            path = '/api/bindings/%s/e/%s/e/%s' % (
                urllib.quote_plus(self.broker_vhost),
                urllib.quote_plus(source_exch),
                urllib.quote_plus(dest_exch)
            )

            body = json.dumps({'routing_key': routing_key, 'arguments': []})

            logger.debug("Sending HTTP POST request to broker %s", path)
            http_conn.request('POST', path, body, auth_headers)

            response = http_conn.getresponse()
            logger.debug("Broker returned response with status %s", response.status)

            if response.status != httplib.CREATED:
                logger.error("Unexpected response status '%s'", response.status)
                raise Exception("Unexpected response status '%s'", response.status)
        except:
            logger.error("Error adding binding via HTTP")
            raise
        finally:
            logger.debug("Closing HTTP connection to broker")
            http_conn.close() 

    def delete_subscription(self, username, token):
        user_exchange_name = username 

        # TODO: See if we can remove this call entirely
        self._ensure_exchanges_exist(self.incoming_exchange_name, user_exchange_name)
        
        self._delete_binding(
            self.incoming_exchange_name,
            user_exchange_name,
            token,
        )
            
    def _delete_binding(self, source_exch, dest_exch, routing_key):
        http_conn = self._get_http_conn()
        try:
            auth_headers = {
                'Authorization': 'Basic ' +
                    base64.b64encode('%s:%s' % \
                        (self.broker_user, self.broker_pass)
                    ),
            }

            path = '/api/bindings/%s/e/%s/e/%s/%s' % (
                urllib.quote_plus(self.broker_vhost),
                urllib.quote_plus(source_exch),
                urllib.quote_plus(dest_exch),
                # Encode twice because binding "properties" are URL-encoded before stored
                urllib.quote_plus(urllib.quote_plus(routing_key))
            )

            logger.debug("Sending HTTP DELETE request to broker %s", path)
            http_conn.request('DELETE', path, '', auth_headers)

            response = http_conn.getresponse()
            logger.debug("Broker returned response with status %s", response.status)

            if response.status != httplib.NO_CONTENT:
                logger.error("Unexpected response status '%s'", response.status)
                raise Exception("Unexpected response status '%s'", response.status)
        except:
            logger.error("Error deleting binding via HTTP")
            raise
        finally:
            logger.debug("Closing HTTP connection to broker")
            http_conn.close()

    # Just moving some duplicate code into a single location.
    # Hopefully we can delete this entirely if we can prove to ourselves that
    # there's no good reason to "assert" the existence of these exchanges other
    # than following proper form (according to AMQP spec).
    def _ensure_exchanges_exist(self, incoming_exchange_name, user_exchange_name):
        conn = self._get_amqp_conn()
        try:
            channel = conn.channel()

            # TODO: Decide if we should remove this call; the incoming exchange
            # should always exist before new_subscription is called
            logger.debug("Declaring incoming exchange %s", incoming_exchange_name)
            channel.exchange_declare(
                exchange=incoming_exchange_name,
                durable=True,
                type='direct',
            )

            # TODO: Decide if we should remove this call; the user exchange
            # should always exist before new_subscription is called
            logger.debug("Declaring user exchange %s", user_exchange_name)
            channel.exchange_declare(
                exchange=user_exchange_name,
                durable=True,
                type='fanout',
            )
        except:
            logger.error("Error ensuring exchanges exist on broker")
            raise
        finally:
            logger.debug("Closing AMQP connection to broker")
            conn.disconnect()

    def publish_message(self, message, token):
        conn = self._get_amqp_conn()
        try:
            channel = conn.channel()

            logger.debug("Declaring incoming exchange '%s'", self.incoming_exchange_name)
            channel.exchange_declare(
                exchange=self.incoming_exchange_name,
                durable=True,
                type='direct',
            )

            logger.debug("Publishing message to exchange '%s'", self.incoming_exchange_name)
            channel.basic_publish(
                exchange=self.incoming_exchange_name,
                routing_key=token,
                body=message,
                properties=pika.BasicProperties(
                    content_type="text/plain",
                ),
            )
        except:
            logger.error("Error publishing message to exchange")
            raise
        finally:
            logger.debug("Disconnecting from message broker")
            conn.disconnect()

    def queue_message(self, message, queue_name):
        conn = self._get_amqp_conn()
        try:
            channel = conn.channel()

            logger.debug("Declaring queue '%s' on message broker", queue_name)
            channel.queue_declare(queue=queue_name)

            logger.debug("Sending message to queue '%s' for processing", queue_name)
            channel.basic_publish(
                exchange='',
                routing_key=queue_name,
                body=request.body,
                properties=pika.BasicProperties(
                    content_type="text/plain",
                ),
            )
        except:
            logger.error("Error queueing message in message broker")
            raise
        finally:
            logger.debug("Disconnecting from message broker")
            conn.disconnect()

    def send_broadcast(self, message, username):
        user_exchange_name = username

        conn = self._get_amqp_conn()
        try:
            channel = conn.channel()

            logger.debug("Declaring exchange '%s'", user_exchange_name)
            channel.exchange_declare(
                exchange=user_exchange_name,
                durable=True,
                type='fanout',
            )

            # Send message to user exchange so all other clients receive it
            logger.debug("Publishing message to exchange '%s'", user_exchange_name)
            channel.basic_publish(
                exchange=user_exchange_name,
                routing_key='',
                body=message,
                properties=pika.BasicProperties(
                    content_type='text/plain',
                ),
            )
        except:
            logger.error("Error sending broadcast message")
            raise
        finally:
            logger.debug("Closing AMQP connection to broker")
            conn.disconnect()

