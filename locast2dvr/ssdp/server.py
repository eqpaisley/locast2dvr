# Licensed under the MIT license
# http://opensource.org/licenses/mit-license.php

# Copyright 2005, Tim Potter <tpot@samba.org>
# Copyright 2006 John-Mark Gurney <gurney_j@resnet.uroegon.edu>
# Copyright (C) 2006 Fluendo, S.A. (www.fluendo.com).
# Copyright 2006,2007,2008,2009 Frank Scholz <coherence@beebits.net>
# Copyright 2016 Erwan Martin <public@fzwte.net>
#
# Implementation of an SSDP server.
#

import random
import socket
import threading
import time
from email.utils import formatdate
from errno import ENOPROTOOPT

from locast2dvr.utils import LoggingHandler

SSDP_PORT = 1900
SSDP_ADDR = '239.255.255.250'
SERVER_ID = 'ZeWaren example SSDP Server'


class SSDPServer(LoggingHandler):
    """A class implementing a SSDP server.  The notify_received and
    searchReceived methods are called when the appropriate type of
    datagram is received by the server."""
    known = {}

    def __init__(self):
        super().__init__()
        self.sock = None

    def start(self):
        threading.Thread(target=self.run).start()

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except socket.error as le:
                # RHEL6 defines SO_REUSEPORT but it doesn't work
                if le.errno == ENOPROTOOPT:
                    pass
                else:
                    raise

        addr = socket.inet_aton(SSDP_ADDR)
        interface = socket.inet_aton('0.0.0.0')
        cmd = socket.IP_ADD_MEMBERSHIP
        self.sock.setsockopt(socket.IPPROTO_IP, cmd, addr + interface)
        self.sock.bind(('0.0.0.0', SSDP_PORT))
        self.sock.settimeout(1)

        while True:
            try:
                data, addr = self.sock.recvfrom(1024)
                self.datagram_received(data, addr)
            except socket.timeout:
                continue
        self.shutdown()

    def shutdown(self):
        for st in self.known:
            if self.known[st]['MANIFESTATION'] == 'local':
                self.do_byebye(st)

    def datagram_received(self, data, host_port):
        """Handle a received multicast datagram."""

        (host, port) = host_port

        try:
            header, payload = data.decode().split('\r\n\r\n')[:2]
        except ValueError as err:
            self.log.error(err)
            return

        lines = header.split('\r\n')
        cmd = lines[0].split(' ')
        lines = [x.replace(': ', ':', 1) for x in lines[1:]]
        lines = [x for x in lines if len(x) > 0]

        headers = [x.split(':', 1) for x in lines]
        headers = dict([(x[0].lower(), x[1]) for x in headers])

        self.log.debug('SSDP command %s %s - from %s:%d' %
                       (cmd[0], cmd[1], host, port))
        self.log.debug('with headers: {}.'.format(headers))
        if cmd[0] == 'M-SEARCH' and cmd[1] == '*':
            # SSDP discovery
            self.discovery_request(headers, (host, port))
        elif cmd[0] == 'NOTIFY' and cmd[1] == '*':
            # SSDP presence
            self.log.debug('NOTIFY *')
        else:
            self.log.warning('Unknown SSDP command %s %s' % (cmd[0], cmd[1]))

    def register(self, manifestation, usn, st, location, server=SERVER_ID, cache_control='max-age=1800', silent=False,
                 host=None):
        """Register a service or device that this SSDP server will
        respond to."""

        self.log.info('Registering %s (%s)' % (st, location))

        self.known[usn] = {}
        self.known[usn]['USN'] = usn
        self.known[usn]['LOCATION'] = location
        self.known[usn]['ST'] = st
        self.known[usn]['EXT'] = ''
        self.known[usn]['SERVER'] = server
        self.known[usn]['CACHE-CONTROL'] = cache_control

        self.known[usn]['MANIFESTATION'] = manifestation
        self.known[usn]['SILENT'] = silent
        self.known[usn]['HOST'] = host
        self.known[usn]['last-seen'] = time.time()

        if manifestation == 'local' and self.sock:
            self.do_notify(usn)

    def unregister(self, usn):
        self.log.debug("Un-registering %s" % usn)
        del self.known[usn]

    def is_known(self, usn):
        return usn in self.known

    def send_it(self, response, destination, delay, usn):
        self.log.debug('send discovery response delayed by %ds for %s to %r' % (
            delay, usn, destination))
        self.log.debug('RESONSE: %r' % response)
        try:
            self.sock.sendto(response.encode(), destination)
        except (AttributeError, socket.error) as msg:
            self.log.warning(
                "failure sending out byebye notification: %r" % msg)

    def discovery_request(self, headers, host_port):
        """Process a discovery request.  The response must be sent to
        the address specified by (host, port)."""

        (host, port) = host_port

        self.log.debug('Discovery request from (%s,%d) for %s' %
                       (host, port, headers['st']))
        self.log.debug('Discovery request for %s' % headers['st'])

        # Do we know about this service?
        for i in list(self.known.values()):
            if i['MANIFESTATION'] == 'remote':
                continue
            if headers['st'] == 'ssdp:all' and i['SILENT']:
                continue
            if i['ST'] == headers['st'] or headers['st'] == 'ssdp:all':
                response = ['HTTP/1.1 200 OK']

                usn = None
                for k, v in list(i.items()):
                    if k == 'USN':
                        usn = v
                    if k not in ('MANIFESTATION', 'SILENT', 'HOST'):
                        response.append('%s: %s' % (k, v))

                if usn:
                    response.append('DATE: %s' % formatdate(
                        timeval=None, localtime=False, usegmt=True))

                    response.extend(('', ''))
                    delay = random.randint(0, int(headers['mx']))

                    self.send_it('\r\n'.join(response),
                                 (host, port), delay, usn)

    def do_notify(self, usn):
        """Do notification"""

        if self.known[usn]['SILENT']:
            return
        self.log.debug('Sending alive notification for %s' % usn)

        resp = [
            'NOTIFY * HTTP/1.1',
            'HOST: %s:%d' % (SSDP_ADDR, SSDP_PORT),
            'NTS: ssdp:alive',
        ]
        stcpy = dict(list(self.known[usn].items()))
        stcpy['NT'] = stcpy['ST']
        del stcpy['ST']
        del stcpy['MANIFESTATION']
        del stcpy['SILENT']
        del stcpy['HOST']
        del stcpy['last-seen']

        resp.extend([': '.join(x) for x in list(stcpy.items())])
        resp.extend(('', ''))
        self.log.debug('do_notify content %r' % resp)
        try:
            self.sock.sendto('\r\n'.join(resp).encode(),
                             (SSDP_ADDR, SSDP_PORT))
            self.sock.sendto('\r\n'.join(resp).encode(),
                             (SSDP_ADDR, SSDP_PORT))
        except (AttributeError, socket.error) as msg:
            self.log.warning(
                "failure sending out alive notification: %r" % msg)

    def do_byebye(self, usn):
        """Do byebye"""

        self.log.debug('Sending byebye notification for %s' % usn)

        resp = [
            'NOTIFY * HTTP/1.1',
            'HOST: %s:%d' % (SSDP_ADDR, SSDP_PORT),
            'NTS: ssdp:byebye',
        ]
        try:
            stcpy = dict(list(self.known[usn].items()))
            stcpy['NT'] = stcpy['ST']
            del stcpy['ST']
            del stcpy['MANIFESTATION']
            del stcpy['SILENT']
            del stcpy['HOST']
            del stcpy['last-seen']
            resp.extend([': '.join(x) for x in list(stcpy.items())])
            resp.extend(('', ''))
            self.log.debug('do_byebye content', resp)
            if self.sock:
                try:
                    self.sock.sendto('\r\n'.join(resp), (SSDP_ADDR, SSDP_PORT))
                except (AttributeError, socket.error) as msg:
                    self.log.error(
                        "failure sending out byebye notification: %r" % msg)
        except KeyError as msg:
            self.log.error("error building byebye notification: %r" % msg)
