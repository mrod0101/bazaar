# Copyright (C) 2006, 2007 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for smart transport"""

# all of this deals with byte strings so this is safe
from cStringIO import StringIO
import os
import socket
import threading
import unittest

from bzrlib import (
        bzrdir,
        errors,
        osutils,
        tests,
        urlutils,
        )
from bzrlib.smart import (
        client,
        medium,
        protocol,
        request,
        request as _mod_request,
        server,
        vfs,
)
from bzrlib.tests.test_smart import TestCaseWithSmartMedium
from bzrlib.transport import (
        get_transport,
        local,
        memory,
        remote,
        )
from bzrlib.transport.http import SmartClientHTTPMediumRequest


class StringIOSSHVendor(object):
    """A SSH vendor that uses StringIO to buffer writes and answer reads."""

    def __init__(self, read_from, write_to):
        self.read_from = read_from
        self.write_to = write_to
        self.calls = []

    def connect_ssh(self, username, password, host, port, command):
        self.calls.append(('connect_ssh', username, password, host, port,
            command))
        return StringIOSSHConnection(self)


class StringIOSSHConnection(object):
    """A SSH connection that uses StringIO to buffer writes and answer reads."""

    def __init__(self, vendor):
        self.vendor = vendor
    
    def close(self):
        self.vendor.calls.append(('close', ))
        
    def get_filelike_channels(self):
        return self.vendor.read_from, self.vendor.write_to


class _InvalidHostnameFeature(tests.Feature):
    """Does 'non_existent.invalid' fail to resolve?
    
    RFC 2606 states that .invalid is reserved for invalid domain names, and
    also underscores are not a valid character in domain names.  Despite this,
    it's possible a badly misconfigured name server might decide to always
    return an address for any name, so this feature allows us to distinguish a
    broken system from a broken test.
    """

    def _probe(self):
        try:
            socket.gethostbyname('non_existent.invalid')
        except socket.gaierror:
            # The host name failed to resolve.  Good.
            return True
        else:
            return False

    def feature_name(self):
        return 'invalid hostname'

InvalidHostnameFeature = _InvalidHostnameFeature()


class SmartClientMediumTests(tests.TestCase):
    """Tests for SmartClientMedium.

    We should create a test scenario for this: we need a server module that
    construct the test-servers (like make_loopsocket_and_medium), and the list
    of SmartClientMedium classes to test.
    """

    def make_loopsocket_and_medium(self):
        """Create a loopback socket for testing, and a medium aimed at it."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        client_medium = medium.SmartTCPClientMedium('127.0.0.1', port)
        return sock, client_medium

    def receive_bytes_on_server(self, sock, bytes):
        """Accept a connection on sock and read 3 bytes.

        The bytes are appended to the list bytes.

        :return: a Thread which is running to do the accept and recv.
        """
        def _receive_bytes_on_server():
            connection, address = sock.accept()
            bytes.append(osutils.recv_all(connection, 3))
            connection.close()
        t = threading.Thread(target=_receive_bytes_on_server)
        t.start()
        return t
    
    def test_construct_smart_stream_medium_client(self):
        # make a new instance of the common base for Stream-like Mediums.
        # this just ensures that the constructor stays parameter-free which
        # is important for reuse : some subclasses will dynamically connect,
        # others are always on, etc.
        client_medium = medium.SmartClientStreamMedium()

    def test_construct_smart_client_medium(self):
        # the base client medium takes no parameters
        client_medium = medium.SmartClientMedium()
    
    def test_construct_smart_simple_pipes_client_medium(self):
        # the SimplePipes client medium takes two pipes:
        # readable pipe, writeable pipe.
        # Constructing one should just save these and do nothing.
        # We test this by passing in None.
        client_medium = medium.SmartSimplePipesClientMedium(None, None)
        
    def test_simple_pipes_client_request_type(self):
        # SimplePipesClient should use SmartClientStreamMediumRequest's.
        client_medium = medium.SmartSimplePipesClientMedium(None, None)
        request = client_medium.get_request()
        self.assertIsInstance(request, medium.SmartClientStreamMediumRequest)

    def test_simple_pipes_client_get_concurrent_requests(self):
        # the simple_pipes client does not support pipelined requests:
        # but it does support serial requests: we construct one after 
        # another is finished. This is a smoke test testing the integration
        # of the SmartClientStreamMediumRequest and the SmartClientStreamMedium
        # classes - as the sibling classes share this logic, they do not have
        # explicit tests for this.
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        request = client_medium.get_request()
        request.finished_writing()
        request.finished_reading()
        request2 = client_medium.get_request()
        request2.finished_writing()
        request2.finished_reading()

    def test_simple_pipes_client__accept_bytes_writes_to_writable(self):
        # accept_bytes writes to the writeable pipe.
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        client_medium._accept_bytes('abc')
        self.assertEqual('abc', output.getvalue())
    
    def test_simple_pipes_client_disconnect_does_nothing(self):
        # calling disconnect does nothing.
        input = StringIO()
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        # send some bytes to ensure disconnecting after activity still does not
        # close.
        client_medium._accept_bytes('abc')
        client_medium.disconnect()
        self.assertFalse(input.closed)
        self.assertFalse(output.closed)

    def test_simple_pipes_client_accept_bytes_after_disconnect(self):
        # calling disconnect on the client does not alter the pipe that
        # accept_bytes writes to.
        input = StringIO()
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        client_medium._accept_bytes('abc')
        client_medium.disconnect()
        client_medium._accept_bytes('abc')
        self.assertFalse(input.closed)
        self.assertFalse(output.closed)
        self.assertEqual('abcabc', output.getvalue())
    
    def test_simple_pipes_client_ignores_disconnect_when_not_connected(self):
        # Doing a disconnect on a new (and thus unconnected) SimplePipes medium
        # does nothing.
        client_medium = medium.SmartSimplePipesClientMedium(None, None)
        client_medium.disconnect()

    def test_simple_pipes_client_can_always_read(self):
        # SmartSimplePipesClientMedium is never disconnected, so read_bytes
        # always tries to read from the underlying pipe.
        input = StringIO('abcdef')
        client_medium = medium.SmartSimplePipesClientMedium(input, None)
        self.assertEqual('abc', client_medium.read_bytes(3))
        client_medium.disconnect()
        self.assertEqual('def', client_medium.read_bytes(3))
        
    def test_simple_pipes_client_supports__flush(self):
        # invoking _flush on a SimplePipesClient should flush the output 
        # pipe. We test this by creating an output pipe that records
        # flush calls made to it.
        from StringIO import StringIO # get regular StringIO
        input = StringIO()
        output = StringIO()
        flush_calls = []
        def logging_flush(): flush_calls.append('flush')
        output.flush = logging_flush
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        # this call is here to ensure we only flush once, not on every
        # _accept_bytes call.
        client_medium._accept_bytes('abc')
        client_medium._flush()
        client_medium.disconnect()
        self.assertEqual(['flush'], flush_calls)

    def test_construct_smart_ssh_client_medium(self):
        # the SSH client medium takes:
        # host, port, username, password, vendor
        # Constructing one should just save these and do nothing.
        # we test this by creating a empty bound socket and constructing
        # a medium.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        unopened_port = sock.getsockname()[1]
        # having vendor be invalid means that if it tries to connect via the
        # vendor it will blow up.
        client_medium = medium.SmartSSHClientMedium('127.0.0.1', unopened_port,
            username=None, password=None, vendor="not a vendor",
            bzr_remote_path='bzr')
        sock.close()

    def test_ssh_client_connects_on_first_use(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        output = StringIO()
        vendor = StringIOSSHVendor(StringIO(), output)
        client_medium = medium.SmartSSHClientMedium(
            'a hostname', 'a port', 'a username', 'a password', vendor, 'bzr')
        client_medium._accept_bytes('abc')
        self.assertEqual('abc', output.getvalue())
        self.assertEqual([('connect_ssh', 'a username', 'a password',
            'a hostname', 'a port',
            ['bzr', 'serve', '--inet', '--directory=/', '--allow-writes'])],
            vendor.calls)
    
    def test_ssh_client_changes_command_when_BZR_REMOTE_PATH_is_set(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        output = StringIO()
        vendor = StringIOSSHVendor(StringIO(), output)
        orig_bzr_remote_path = os.environ.get('BZR_REMOTE_PATH')
        def cleanup_environ():
            osutils.set_or_unset_env('BZR_REMOTE_PATH', orig_bzr_remote_path)
        self.addCleanup(cleanup_environ)
        os.environ['BZR_REMOTE_PATH'] = 'fugly'
        client_medium = self.callDeprecated(
            ['bzr_remote_path is required as of bzr 0.92'],
            medium.SmartSSHClientMedium, 'a hostname', 'a port', 'a username',
            'a password', vendor)
        client_medium._accept_bytes('abc')
        self.assertEqual('abc', output.getvalue())
        self.assertEqual([('connect_ssh', 'a username', 'a password',
            'a hostname', 'a port',
            ['fugly', 'serve', '--inet', '--directory=/', '--allow-writes'])],
            vendor.calls)
    
    def test_ssh_client_changes_command_when_bzr_remote_path_passed(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        output = StringIO()
        vendor = StringIOSSHVendor(StringIO(), output)
        client_medium = medium.SmartSSHClientMedium('a hostname', 'a port',
            'a username', 'a password', vendor, bzr_remote_path='fugly')
        client_medium._accept_bytes('abc')
        self.assertEqual('abc', output.getvalue())
        self.assertEqual([('connect_ssh', 'a username', 'a password',
            'a hostname', 'a port',
            ['fugly', 'serve', '--inet', '--directory=/', '--allow-writes'])],
            vendor.calls)

    def test_ssh_client_disconnect_does_so(self):
        # calling disconnect should disconnect both the read_from and write_to
        # file-like object it from the ssh connection.
        input = StringIO()
        output = StringIO()
        vendor = StringIOSSHVendor(input, output)
        client_medium = medium.SmartSSHClientMedium('a hostname',
                                                    vendor=vendor,
                                                    bzr_remote_path='bzr')
        client_medium._accept_bytes('abc')
        client_medium.disconnect()
        self.assertTrue(input.closed)
        self.assertTrue(output.closed)
        self.assertEqual([
            ('connect_ssh', None, None, 'a hostname', None,
            ['bzr', 'serve', '--inet', '--directory=/', '--allow-writes']),
            ('close', ),
            ],
            vendor.calls)

    def test_ssh_client_disconnect_allows_reconnection(self):
        # calling disconnect on the client terminates the connection, but should
        # not prevent additional connections occuring.
        # we test this by initiating a second connection after doing a
        # disconnect.
        input = StringIO()
        output = StringIO()
        vendor = StringIOSSHVendor(input, output)
        client_medium = medium.SmartSSHClientMedium('a hostname',
            vendor=vendor, bzr_remote_path='bzr')
        client_medium._accept_bytes('abc')
        client_medium.disconnect()
        # the disconnect has closed output, so we need a new output for the
        # new connection to write to.
        input2 = StringIO()
        output2 = StringIO()
        vendor.read_from = input2
        vendor.write_to = output2
        client_medium._accept_bytes('abc')
        client_medium.disconnect()
        self.assertTrue(input.closed)
        self.assertTrue(output.closed)
        self.assertTrue(input2.closed)
        self.assertTrue(output2.closed)
        self.assertEqual([
            ('connect_ssh', None, None, 'a hostname', None,
            ['bzr', 'serve', '--inet', '--directory=/', '--allow-writes']),
            ('close', ),
            ('connect_ssh', None, None, 'a hostname', None,
            ['bzr', 'serve', '--inet', '--directory=/', '--allow-writes']),
            ('close', ),
            ],
            vendor.calls)
    
    def test_ssh_client_ignores_disconnect_when_not_connected(self):
        # Doing a disconnect on a new (and thus unconnected) SSH medium
        # does not fail.  It's ok to disconnect an unconnected medium.
        client_medium = medium.SmartSSHClientMedium(None,
                                                    bzr_remote_path='bzr')
        client_medium.disconnect()

    def test_ssh_client_raises_on_read_when_not_connected(self):
        # Doing a read on a new (and thus unconnected) SSH medium raises
        # MediumNotConnected.
        client_medium = medium.SmartSSHClientMedium(None,
                                                    bzr_remote_path='bzr')
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes,
                          0)
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes,
                          1)

    def test_ssh_client_supports__flush(self):
        # invoking _flush on a SSHClientMedium should flush the output 
        # pipe. We test this by creating an output pipe that records
        # flush calls made to it.
        from StringIO import StringIO # get regular StringIO
        input = StringIO()
        output = StringIO()
        flush_calls = []
        def logging_flush(): flush_calls.append('flush')
        output.flush = logging_flush
        vendor = StringIOSSHVendor(input, output)
        client_medium = medium.SmartSSHClientMedium('a hostname',
                                                    vendor=vendor,
                                                    bzr_remote_path='bzr')
        # this call is here to ensure we only flush once, not on every
        # _accept_bytes call.
        client_medium._accept_bytes('abc')
        client_medium._flush()
        client_medium.disconnect()
        self.assertEqual(['flush'], flush_calls)
        
    def test_construct_smart_tcp_client_medium(self):
        # the TCP client medium takes a host and a port.  Constructing it won't
        # connect to anything.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        unopened_port = sock.getsockname()[1]
        client_medium = medium.SmartTCPClientMedium('127.0.0.1', unopened_port)
        sock.close()

    def test_tcp_client_connects_on_first_use(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        sock, medium = self.make_loopsocket_and_medium()
        bytes = []
        t = self.receive_bytes_on_server(sock, bytes)
        medium.accept_bytes('abc')
        t.join()
        sock.close()
        self.assertEqual(['abc'], bytes)
    
    def test_tcp_client_disconnect_does_so(self):
        # calling disconnect on the client terminates the connection.
        # we test this by forcing a short read during a socket.MSG_WAITALL
        # call: write 2 bytes, try to read 3, and then the client disconnects.
        sock, medium = self.make_loopsocket_and_medium()
        bytes = []
        t = self.receive_bytes_on_server(sock, bytes)
        medium.accept_bytes('ab')
        medium.disconnect()
        t.join()
        sock.close()
        self.assertEqual(['ab'], bytes)
        # now disconnect again: this should not do anything, if disconnection
        # really did disconnect.
        medium.disconnect()

    
    def test_tcp_client_ignores_disconnect_when_not_connected(self):
        # Doing a disconnect on a new (and thus unconnected) TCP medium
        # does not fail.  It's ok to disconnect an unconnected medium.
        client_medium = medium.SmartTCPClientMedium(None, None)
        client_medium.disconnect()

    def test_tcp_client_raises_on_read_when_not_connected(self):
        # Doing a read on a new (and thus unconnected) TCP medium raises
        # MediumNotConnected.
        client_medium = medium.SmartTCPClientMedium(None, None)
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes, 0)
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes, 1)

    def test_tcp_client_supports__flush(self):
        # invoking _flush on a TCPClientMedium should do something useful.
        # RBC 20060922 not sure how to test/tell in this case.
        sock, medium = self.make_loopsocket_and_medium()
        bytes = []
        t = self.receive_bytes_on_server(sock, bytes)
        # try with nothing buffered
        medium._flush()
        medium._accept_bytes('ab')
        # and with something sent.
        medium._flush()
        medium.disconnect()
        t.join()
        sock.close()
        self.assertEqual(['ab'], bytes)
        # now disconnect again : this should not do anything, if disconnection
        # really did disconnect.
        medium.disconnect()

    def test_tcp_client_host_unknown_connection_error(self):
        self.requireFeature(InvalidHostnameFeature)
        client_medium = medium.SmartTCPClientMedium(
            'non_existent.invalid', 4155)
        self.assertRaises(
            errors.ConnectionError, client_medium._ensure_connection)


class TestSmartClientStreamMediumRequest(tests.TestCase):
    """Tests the for SmartClientStreamMediumRequest.
    
    SmartClientStreamMediumRequest is a helper for the three stream based 
    mediums: TCP, SSH, SimplePipes, so we only test it once, and then test that
    those three mediums implement the interface it expects.
    """

    def test_accept_bytes_after_finished_writing_errors(self):
        # calling accept_bytes after calling finished_writing raises 
        # WritingCompleted to prevent bad assumptions on stream environments
        # breaking the needs of message-based environments.
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        self.assertRaises(errors.WritingCompleted, request.accept_bytes, None)

    def test_accept_bytes(self):
        # accept bytes should invoke _accept_bytes on the stream medium.
        # we test this by using the SimplePipes medium - the most trivial one
        # and checking that the pipes get the data.
        input = StringIO()
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.accept_bytes('123')
        request.finished_writing()
        request.finished_reading()
        self.assertEqual('', input.getvalue())
        self.assertEqual('123', output.getvalue())

    def test_construct_sets_stream_request(self):
        # constructing a SmartClientStreamMediumRequest on a StreamMedium sets
        # the current request to the new SmartClientStreamMediumRequest
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        self.assertIs(client_medium._current_request, request)

    def test_construct_while_another_request_active_throws(self):
        # constructing a SmartClientStreamMediumRequest on a StreamMedium with
        # a non-None _current_request raises TooManyConcurrentRequests.
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        client_medium._current_request = "a"
        self.assertRaises(errors.TooManyConcurrentRequests,
            medium.SmartClientStreamMediumRequest, client_medium)

    def test_finished_read_clears_current_request(self):
        # calling finished_reading clears the current request from the requests
        # medium
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        request.finished_reading()
        self.assertEqual(None, client_medium._current_request)

    def test_finished_read_before_finished_write_errors(self):
        # calling finished_reading before calling finished_writing triggers a
        # WritingNotComplete error.
        client_medium = medium.SmartSimplePipesClientMedium(None, None)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        self.assertRaises(errors.WritingNotComplete, request.finished_reading)
        
    def test_read_bytes(self):
        # read bytes should invoke _read_bytes on the stream medium.
        # we test this by using the SimplePipes medium - the most trivial one
        # and checking that the data is supplied. Its possible that a 
        # faulty implementation could poke at the pipe variables them selves,
        # but we trust that this will be caught as it will break the integration
        # smoke tests.
        input = StringIO('321')
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        self.assertEqual('321', request.read_bytes(3))
        request.finished_reading()
        self.assertEqual('', input.read())
        self.assertEqual('', output.getvalue())

    def test_read_bytes_before_finished_write_errors(self):
        # calling read_bytes before calling finished_writing triggers a
        # WritingNotComplete error because the Smart protocol is designed to be
        # compatible with strict message based protocols like HTTP where the
        # request cannot be submitted until the writing has completed.
        client_medium = medium.SmartSimplePipesClientMedium(None, None)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        self.assertRaises(errors.WritingNotComplete, request.read_bytes, None)

    def test_read_bytes_after_finished_reading_errors(self):
        # calling read_bytes after calling finished_reading raises 
        # ReadingCompleted to prevent bad assumptions on stream environments
        # breaking the needs of message-based environments.
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        request.finished_reading()
        self.assertRaises(errors.ReadingCompleted, request.read_bytes, None)


class RemoteTransportTests(TestCaseWithSmartMedium):

    def test_plausible_url(self):
        self.assert_(self.get_url().startswith('bzr://'))

    def test_probe_transport(self):
        t = self.get_transport()
        self.assertIsInstance(t, remote.RemoteTransport)

    def test_get_medium_from_transport(self):
        """Remote transport has a medium always, which it can return."""
        t = self.get_transport()
        client_medium = t.get_smart_medium()
        self.assertIsInstance(client_medium, medium.SmartClientMedium)


class ErrorRaisingProtocol(object):

    def __init__(self, exception):
        self.exception = exception

    def next_read_size(self):
        raise self.exception


class SampleRequest(object):
    
    def __init__(self, expected_bytes):
        self.accepted_bytes = ''
        self._finished_reading = False
        self.expected_bytes = expected_bytes
        self.excess_buffer = ''

    def accept_bytes(self, bytes):
        self.accepted_bytes += bytes
        if self.accepted_bytes.startswith(self.expected_bytes):
            self._finished_reading = True
            self.excess_buffer = self.accepted_bytes[len(self.expected_bytes):]

    def next_read_size(self):
        if self._finished_reading:
            return 0
        else:
            return 1


class TestSmartServerStreamMedium(tests.TestCase):

    def setUp(self):
        super(TestSmartServerStreamMedium, self).setUp()
        self._captureVar('BZR_NO_SMART_VFS', None)

    def portable_socket_pair(self):
        """Return a pair of TCP sockets connected to each other.
        
        Unlike socket.socketpair, this should work on Windows.
        """
        listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_sock.bind(('127.0.0.1', 0))
        listen_sock.listen(1)
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.connect(listen_sock.getsockname())
        server_sock, addr = listen_sock.accept()
        listen_sock.close()
        return server_sock, client_sock
    
    def test_smart_query_version(self):
        """Feed a canned query version to a server"""
        # wire-to-wire, using the whole stack
        to_server = StringIO('hello\n')
        from_server = StringIO()
        transport = local.LocalTransport(urlutils.local_path_to_url('/'))
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, transport)
        smart_protocol = protocol.SmartServerRequestProtocolOne(transport,
                from_server.write)
        server._serve_one_request(smart_protocol)
        self.assertEqual('ok\0013\n',
                         from_server.getvalue())

    def test_response_to_canned_get(self):
        transport = memory.MemoryTransport('memory:///')
        transport.put_bytes('testfile', 'contents\nof\nfile\n')
        to_server = StringIO('get\001./testfile\n')
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, transport)
        smart_protocol = protocol.SmartServerRequestProtocolOne(transport,
                from_server.write)
        server._serve_one_request(smart_protocol)
        self.assertEqual('ok\n'
                         '17\n'
                         'contents\nof\nfile\n'
                         'done\n',
                         from_server.getvalue())

    def test_response_to_canned_get_of_utf8(self):
        # wire-to-wire, using the whole stack, with a UTF-8 filename.
        transport = memory.MemoryTransport('memory:///')
        utf8_filename = u'testfile\N{INTERROBANG}'.encode('utf-8')
        transport.put_bytes(utf8_filename, 'contents\nof\nfile\n')
        to_server = StringIO('get\001' + utf8_filename + '\n')
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, transport)
        smart_protocol = protocol.SmartServerRequestProtocolOne(transport,
                from_server.write)
        server._serve_one_request(smart_protocol)
        self.assertEqual('ok\n'
                         '17\n'
                         'contents\nof\nfile\n'
                         'done\n',
                         from_server.getvalue())

    def test_pipe_like_stream_with_bulk_data(self):
        sample_request_bytes = 'command\n9\nbulk datadone\n'
        to_server = StringIO(sample_request_bytes)
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, None)
        sample_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        server._serve_one_request(sample_protocol)
        self.assertEqual('', from_server.getvalue())
        self.assertEqual(sample_request_bytes, sample_protocol.accepted_bytes)
        self.assertFalse(server.finished)

    def test_socket_stream_with_bulk_data(self):
        sample_request_bytes = 'command\n9\nbulk datadone\n'
        server_sock, client_sock = self.portable_socket_pair()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        sample_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        client_sock.sendall(sample_request_bytes)
        server._serve_one_request(sample_protocol)
        server_sock.close()
        self.assertEqual('', client_sock.recv(1))
        self.assertEqual(sample_request_bytes, sample_protocol.accepted_bytes)
        self.assertFalse(server.finished)

    def test_pipe_like_stream_shutdown_detection(self):
        to_server = StringIO('')
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(to_server, from_server, None)
        server._serve_one_request(SampleRequest('x'))
        self.assertTrue(server.finished)
        
    def test_socket_stream_shutdown_detection(self):
        server_sock, client_sock = self.portable_socket_pair()
        client_sock.close()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        server._serve_one_request(SampleRequest('x'))
        self.assertTrue(server.finished)
        
    def test_socket_stream_incomplete_request(self):
        """The medium should still construct the right protocol version even if
        the initial read only reads part of the request.

        Specifically, it should correctly read the protocol version line even
        if the partial read doesn't end in a newline.  An older, naive
        implementation of _get_line in the server used to have a bug in that
        case.
        """
        incomplete_request_bytes = protocol.REQUEST_VERSION_TWO + 'hel'
        rest_of_request_bytes = 'lo\n'
        expected_response = (
            protocol.RESPONSE_VERSION_TWO + 'success\nok\x013\n')
        server_sock, client_sock = self.portable_socket_pair()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        client_sock.sendall(incomplete_request_bytes)
        server_protocol = server._build_protocol()
        client_sock.sendall(rest_of_request_bytes)
        server._serve_one_request(server_protocol)
        server_sock.close()
        self.assertEqual(expected_response, client_sock.recv(50),
                         "Not a version 2 response to 'hello' request.")
        self.assertEqual('', client_sock.recv(1))

    def test_pipe_stream_incomplete_request(self):
        """The medium should still construct the right protocol version even if
        the initial read only reads part of the request.

        Specifically, it should correctly read the protocol version line even
        if the partial read doesn't end in a newline.  An older, naive
        implementation of _get_line in the server used to have a bug in that
        case.
        """
        incomplete_request_bytes = protocol.REQUEST_VERSION_TWO + 'hel'
        rest_of_request_bytes = 'lo\n'
        expected_response = (
            protocol.RESPONSE_VERSION_TWO + 'success\nok\x013\n')
        # Make a pair of pipes, to and from the server
        to_server, to_server_w = os.pipe()
        from_server_r, from_server = os.pipe()
        to_server = os.fdopen(to_server, 'r', 0)
        to_server_w = os.fdopen(to_server_w, 'w', 0)
        from_server_r = os.fdopen(from_server_r, 'r', 0)
        from_server = os.fdopen(from_server, 'w', 0)
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, None)
        # Like test_socket_stream_incomplete_request, write an incomplete
        # request (that does not end in '\n') and build a protocol from it.
        to_server_w.write(incomplete_request_bytes)
        server_protocol = server._build_protocol()
        # Send the rest of the request, and finish serving it.
        to_server_w.write(rest_of_request_bytes)
        server._serve_one_request(server_protocol)
        to_server_w.close()
        from_server.close()
        self.assertEqual(expected_response, from_server_r.read(),
                         "Not a version 2 response to 'hello' request.")
        self.assertEqual('', from_server_r.read(1))
        from_server_r.close()
        to_server.close()

    def test_pipe_like_stream_with_two_requests(self):
        # If two requests are read in one go, then two calls to
        # _serve_one_request should still process both of them as if they had
        # been received seperately.
        sample_request_bytes = 'command\n'
        to_server = StringIO(sample_request_bytes * 2)
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, None)
        first_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        server._serve_one_request(first_protocol)
        self.assertEqual(0, first_protocol.next_read_size())
        self.assertEqual('', from_server.getvalue())
        self.assertFalse(server.finished)
        # Make a new protocol, call _serve_one_request with it to collect the
        # second request.
        second_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        server._serve_one_request(second_protocol)
        self.assertEqual('', from_server.getvalue())
        self.assertEqual(sample_request_bytes, second_protocol.accepted_bytes)
        self.assertFalse(server.finished)
        
    def test_socket_stream_with_two_requests(self):
        # If two requests are read in one go, then two calls to
        # _serve_one_request should still process both of them as if they had
        # been received seperately.
        sample_request_bytes = 'command\n'
        server_sock, client_sock = self.portable_socket_pair()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        first_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        # Put two whole requests on the wire.
        client_sock.sendall(sample_request_bytes * 2)
        server._serve_one_request(first_protocol)
        self.assertEqual(0, first_protocol.next_read_size())
        self.assertFalse(server.finished)
        # Make a new protocol, call _serve_one_request with it to collect the
        # second request.
        second_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        stream_still_open = server._serve_one_request(second_protocol)
        self.assertEqual(sample_request_bytes, second_protocol.accepted_bytes)
        self.assertFalse(server.finished)
        server_sock.close()
        self.assertEqual('', client_sock.recv(1))

    def test_pipe_like_stream_error_handling(self):
        # Use plain python StringIO so we can monkey-patch the close method to
        # not discard the contents.
        from StringIO import StringIO
        to_server = StringIO('')
        from_server = StringIO()
        self.closed = False
        def close():
            self.closed = True
        from_server.close = close
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, None)
        fake_protocol = ErrorRaisingProtocol(Exception('boom'))
        server._serve_one_request(fake_protocol)
        self.assertEqual('', from_server.getvalue())
        self.assertTrue(self.closed)
        self.assertTrue(server.finished)
        
    def test_socket_stream_error_handling(self):
        server_sock, client_sock = self.portable_socket_pair()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        fake_protocol = ErrorRaisingProtocol(Exception('boom'))
        server._serve_one_request(fake_protocol)
        # recv should not block, because the other end of the socket has been
        # closed.
        self.assertEqual('', client_sock.recv(1))
        self.assertTrue(server.finished)
        
    def test_pipe_like_stream_keyboard_interrupt_handling(self):
        to_server = StringIO('')
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, None)
        fake_protocol = ErrorRaisingProtocol(KeyboardInterrupt('boom'))
        self.assertRaises(
            KeyboardInterrupt, server._serve_one_request, fake_protocol)
        self.assertEqual('', from_server.getvalue())

    def test_socket_stream_keyboard_interrupt_handling(self):
        server_sock, client_sock = self.portable_socket_pair()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        fake_protocol = ErrorRaisingProtocol(KeyboardInterrupt('boom'))
        self.assertRaises(
            KeyboardInterrupt, server._serve_one_request, fake_protocol)
        server_sock.close()
        self.assertEqual('', client_sock.recv(1))

    def build_protocol_pipe_like(self, bytes):
        to_server = StringIO(bytes)
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, None)
        return server._build_protocol()

    def build_protocol_socket(self, bytes):
        server_sock, client_sock = self.portable_socket_pair()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        client_sock.sendall(bytes)
        client_sock.close()
        return server._build_protocol()

    def assertProtocolOne(self, server_protocol):
        # Use assertIs because assertIsInstance will wrongly pass
        # SmartServerRequestProtocolTwo (because it subclasses
        # SmartServerRequestProtocolOne).
        self.assertIs(
            type(server_protocol), protocol.SmartServerRequestProtocolOne)

    def assertProtocolTwo(self, server_protocol):
        self.assertIsInstance(
            server_protocol, protocol.SmartServerRequestProtocolTwo)

    def test_pipe_like_build_protocol_empty_bytes(self):
        # Any empty request (i.e. no bytes) is detected as protocol version one.
        server_protocol = self.build_protocol_pipe_like('')
        self.assertProtocolOne(server_protocol)
        
    def test_socket_like_build_protocol_empty_bytes(self):
        # Any empty request (i.e. no bytes) is detected as protocol version one.
        server_protocol = self.build_protocol_socket('')
        self.assertProtocolOne(server_protocol)

    def test_pipe_like_build_protocol_non_two(self):
        # A request that doesn't start with "bzr request 2\n" is version one.
        server_protocol = self.build_protocol_pipe_like('abc\n')
        self.assertProtocolOne(server_protocol)

    def test_socket_build_protocol_non_two(self):
        # A request that doesn't start with "bzr request 2\n" is version one.
        server_protocol = self.build_protocol_socket('abc\n')
        self.assertProtocolOne(server_protocol)

    def test_pipe_like_build_protocol_two(self):
        # A request that starts with "bzr request 2\n" is version two.
        server_protocol = self.build_protocol_pipe_like('bzr request 2\n')
        self.assertProtocolTwo(server_protocol)

    def test_socket_build_protocol_two(self):
        # A request that starts with "bzr request 2\n" is version two.
        server_protocol = self.build_protocol_socket('bzr request 2\n')
        self.assertProtocolTwo(server_protocol)
        

class TestSmartTCPServer(tests.TestCase):

    def test_get_error_unexpected(self):
        """Error reported by server with no specific representation"""
        self._captureVar('BZR_NO_SMART_VFS', None)
        class FlakyTransport(object):
            base = 'a_url'
            def external_url(self):
                return self.base
            def get_bytes(self, path):
                raise Exception("some random exception from inside server")
        smart_server = server.SmartTCPServer(backing_transport=FlakyTransport())
        smart_server.start_background_thread()
        try:
            transport = remote.RemoteTCPTransport(smart_server.get_url())
            try:
                transport.get('something')
            except errors.TransportError, e:
                self.assertContainsRe(str(e), 'some random exception')
            else:
                self.fail("get did not raise expected error")
            transport.disconnect()
        finally:
            smart_server.stop_background_thread()


class SmartTCPTests(tests.TestCase):
    """Tests for connection/end to end behaviour using the TCP server.

    All of these tests are run with a server running on another thread serving
    a MemoryTransport, and a connection to it already open.

    the server is obtained by calling self.setUpServer(readonly=False).
    """

    def setUpServer(self, readonly=False, backing_transport=None):
        """Setup the server.

        :param readonly: Create a readonly server.
        """
        if not backing_transport:
            self.backing_transport = memory.MemoryTransport()
        else:
            self.backing_transport = backing_transport
        if readonly:
            self.real_backing_transport = self.backing_transport
            self.backing_transport = get_transport("readonly+" + self.backing_transport.abspath('.'))
        self.server = server.SmartTCPServer(self.backing_transport)
        self.server.start_background_thread()
        self.transport = remote.RemoteTCPTransport(self.server.get_url())
        self.addCleanup(self.tearDownServer)

    def tearDownServer(self):
        if getattr(self, 'transport', None):
            self.transport.disconnect()
            del self.transport
        if getattr(self, 'server', None):
            self.server.stop_background_thread()
            del self.server


class TestServerSocketUsage(SmartTCPTests):

    def test_server_setup_teardown(self):
        """It should be safe to teardown the server with no requests."""
        self.setUpServer()
        server = self.server
        transport = remote.RemoteTCPTransport(self.server.get_url())
        self.tearDownServer()
        self.assertRaises(errors.ConnectionError, transport.has, '.')

    def test_server_closes_listening_sock_on_shutdown_after_request(self):
        """The server should close its listening socket when it's stopped."""
        self.setUpServer()
        server = self.server
        self.transport.has('.')
        self.tearDownServer()
        # if the listening socket has closed, we should get a BADFD error
        # when connecting, rather than a hang.
        transport = remote.RemoteTCPTransport(server.get_url())
        self.assertRaises(errors.ConnectionError, transport.has, '.')


class WritableEndToEndTests(SmartTCPTests):
    """Client to server tests that require a writable transport."""

    def setUp(self):
        super(WritableEndToEndTests, self).setUp()
        self.setUpServer()

    def test_start_tcp_server(self):
        url = self.server.get_url()
        self.assertContainsRe(url, r'^bzr://127\.0\.0\.1:[0-9]{2,}/')

    def test_smart_transport_has(self):
        """Checking for file existence over smart."""
        self._captureVar('BZR_NO_SMART_VFS', None)
        self.backing_transport.put_bytes("foo", "contents of foo\n")
        self.assertTrue(self.transport.has("foo"))
        self.assertFalse(self.transport.has("non-foo"))

    def test_smart_transport_get(self):
        """Read back a file over smart."""
        self._captureVar('BZR_NO_SMART_VFS', None)
        self.backing_transport.put_bytes("foo", "contents\nof\nfoo\n")
        fp = self.transport.get("foo")
        self.assertEqual('contents\nof\nfoo\n', fp.read())

    def test_get_error_enoent(self):
        """Error reported from server getting nonexistent file."""
        # The path in a raised NoSuchFile exception should be the precise path
        # asked for by the client. This gives meaningful and unsurprising errors
        # for users.
        self._captureVar('BZR_NO_SMART_VFS', None)
        try:
            self.transport.get('not%20a%20file')
        except errors.NoSuchFile, e:
            self.assertEqual('not%20a%20file', e.path)
        else:
            self.fail("get did not raise expected error")

    def test_simple_clone_conn(self):
        """Test that cloning reuses the same connection."""
        # we create a real connection not a loopback one, but it will use the
        # same server and pipes
        conn2 = self.transport.clone('.')
        self.assertIs(self.transport.get_smart_medium(),
                      conn2.get_smart_medium())

    def test__remote_path(self):
        self.assertEquals('/foo/bar',
                          self.transport._remote_path('foo/bar'))

    def test_clone_changes_base(self):
        """Cloning transport produces one with a new base location"""
        conn2 = self.transport.clone('subdir')
        self.assertEquals(self.transport.base + 'subdir/',
                          conn2.base)

    def test_open_dir(self):
        """Test changing directory"""
        self._captureVar('BZR_NO_SMART_VFS', None)
        transport = self.transport
        self.backing_transport.mkdir('toffee')
        self.backing_transport.mkdir('toffee/apple')
        self.assertEquals('/toffee', transport._remote_path('toffee'))
        toffee_trans = transport.clone('toffee')
        # Check that each transport has only the contents of its directory
        # directly visible. If state was being held in the wrong object, it's
        # conceivable that cloning a transport would alter the state of the
        # cloned-from transport.
        self.assertTrue(transport.has('toffee'))
        self.assertFalse(toffee_trans.has('toffee'))
        self.assertFalse(transport.has('apple'))
        self.assertTrue(toffee_trans.has('apple'))

    def test_open_bzrdir(self):
        """Open an existing bzrdir over smart transport"""
        transport = self.transport
        t = self.backing_transport
        bzrdir.BzrDirFormat.get_default_format().initialize_on_transport(t)
        result_dir = bzrdir.BzrDir.open_containing_from_transport(transport)


class ReadOnlyEndToEndTests(SmartTCPTests):
    """Tests from the client to the server using a readonly backing transport."""

    def test_mkdir_error_readonly(self):
        """TransportNotPossible should be preserved from the backing transport."""
        self._captureVar('BZR_NO_SMART_VFS', None)
        self.setUpServer(readonly=True)
        self.assertRaises(errors.TransportNotPossible, self.transport.mkdir,
            'foo')


class TestServerHooks(SmartTCPTests):

    def capture_server_call(self, backing_urls, public_url):
        """Record a server_started|stopped hook firing."""
        self.hook_calls.append((backing_urls, public_url))

    def test_server_started_hook_memory(self):
        """The server_started hook fires when the server is started."""
        self.hook_calls = []
        server.SmartTCPServer.hooks.install_hook('server_started',
            self.capture_server_call)
        self.setUpServer()
        # at this point, the server will be starting a thread up.
        # there is no indicator at the moment, so bodge it by doing a request.
        self.transport.has('.')
        # The default test server uses MemoryTransport and that has no external
        # url:
        self.assertEqual([([self.backing_transport.base], self.transport.base)],
            self.hook_calls)

    def test_server_started_hook_file(self):
        """The server_started hook fires when the server is started."""
        self.hook_calls = []
        server.SmartTCPServer.hooks.install_hook('server_started',
            self.capture_server_call)
        self.setUpServer(backing_transport=get_transport("."))
        # at this point, the server will be starting a thread up.
        # there is no indicator at the moment, so bodge it by doing a request.
        self.transport.has('.')
        # The default test server uses MemoryTransport and that has no external
        # url:
        self.assertEqual([([
            self.backing_transport.base, self.backing_transport.external_url()],
             self.transport.base)],
            self.hook_calls)

    def test_server_stopped_hook_simple_memory(self):
        """The server_stopped hook fires when the server is stopped."""
        self.hook_calls = []
        server.SmartTCPServer.hooks.install_hook('server_stopped',
            self.capture_server_call)
        self.setUpServer()
        result = [([self.backing_transport.base], self.transport.base)]
        # check the stopping message isn't emitted up front.
        self.assertEqual([], self.hook_calls)
        # nor after a single message
        self.transport.has('.')
        self.assertEqual([], self.hook_calls)
        # clean up the server
        self.tearDownServer()
        # now it should have fired.
        self.assertEqual(result, self.hook_calls)

    def test_server_stopped_hook_simple_file(self):
        """The server_stopped hook fires when the server is stopped."""
        self.hook_calls = []
        server.SmartTCPServer.hooks.install_hook('server_stopped',
            self.capture_server_call)
        self.setUpServer(backing_transport=get_transport("."))
        result = [(
            [self.backing_transport.base, self.backing_transport.external_url()]
            , self.transport.base)]
        # check the stopping message isn't emitted up front.
        self.assertEqual([], self.hook_calls)
        # nor after a single message
        self.transport.has('.')
        self.assertEqual([], self.hook_calls)
        # clean up the server
        self.tearDownServer()
        # now it should have fired.
        self.assertEqual(result, self.hook_calls)

# TODO: test that when the server suffers an exception that it calls the
# server-stopped hook.


class SmartServerCommandTests(tests.TestCaseWithTransport):
    """Tests that call directly into the command objects, bypassing the network
    and the request dispatching.

    Note: these tests are rudimentary versions of the command object tests in
    test_remote.py.
    """
        
    def test_hello(self):
        cmd = request.HelloRequest(None)
        response = cmd.execute()
        self.assertEqual(('ok', '3'), response.args)
        self.assertEqual(None, response.body)
        
    def test_get_bundle(self):
        from bzrlib.bundle import serializer
        wt = self.make_branch_and_tree('.')
        self.build_tree_contents([('hello', 'hello world')])
        wt.add('hello')
        rev_id = wt.commit('add hello')
        
        cmd = request.GetBundleRequest(self.get_transport())
        response = cmd.execute('.', rev_id)
        bundle = serializer.read_bundle(StringIO(response.body))
        self.assertEqual((), response.args)


class SmartServerRequestHandlerTests(tests.TestCaseWithTransport):
    """Test that call directly into the handler logic, bypassing the network."""

    def setUp(self):
        super(SmartServerRequestHandlerTests, self).setUp()
        self._captureVar('BZR_NO_SMART_VFS', None)

    def build_handler(self, transport):
        """Returns a handler for the commands in protocol version one."""
        return request.SmartServerRequestHandler(transport,
                                                 request.request_handlers)

    def test_construct_request_handler(self):
        """Constructing a request handler should be easy and set defaults."""
        handler = request.SmartServerRequestHandler(None, None)
        self.assertFalse(handler.finished_reading)

    def test_hello(self):
        handler = self.build_handler(None)
        handler.dispatch_command('hello', ())
        self.assertEqual(('ok', '3'), handler.response.args)
        self.assertEqual(None, handler.response.body)
        
    def test_disable_vfs_handler_classes_via_environment(self):
        # VFS handler classes will raise an error from "execute" if
        # BZR_NO_SMART_VFS is set.
        handler = vfs.HasRequest(None)
        # set environment variable after construction to make sure it's
        # examined.
        # Note that we can safely clobber BZR_NO_SMART_VFS here, because setUp
        # has called _captureVar, so it will be restored to the right state
        # afterwards.
        os.environ['BZR_NO_SMART_VFS'] = ''
        self.assertRaises(errors.DisabledMethod, handler.execute)

    def test_readonly_exception_becomes_transport_not_possible(self):
        """The response for a read-only error is ('ReadOnlyError')."""
        handler = self.build_handler(self.get_readonly_transport())
        # send a mkdir for foo, with no explicit mode - should fail.
        handler.dispatch_command('mkdir', ('foo', ''))
        # and the failure should be an explicit ReadOnlyError
        self.assertEqual(("ReadOnlyError", ), handler.response.args)
        # XXX: TODO: test that other TransportNotPossible errors are
        # presented as TransportNotPossible - not possible to do that
        # until I figure out how to trigger that relatively cleanly via
        # the api. RBC 20060918

    def test_hello_has_finished_body_on_dispatch(self):
        """The 'hello' command should set finished_reading."""
        handler = self.build_handler(None)
        handler.dispatch_command('hello', ())
        self.assertTrue(handler.finished_reading)
        self.assertNotEqual(None, handler.response)

    def test_put_bytes_non_atomic(self):
        """'put_...' should set finished_reading after reading the bytes."""
        handler = self.build_handler(self.get_transport())
        handler.dispatch_command('put_non_atomic', ('a-file', '', 'F', ''))
        self.assertFalse(handler.finished_reading)
        handler.accept_body('1234')
        self.assertFalse(handler.finished_reading)
        handler.accept_body('5678')
        handler.end_of_body()
        self.assertTrue(handler.finished_reading)
        self.assertEqual(('ok', ), handler.response.args)
        self.assertEqual(None, handler.response.body)
        
    def test_readv_accept_body(self):
        """'readv' should set finished_reading after reading offsets."""
        self.build_tree(['a-file'])
        handler = self.build_handler(self.get_readonly_transport())
        handler.dispatch_command('readv', ('a-file', ))
        self.assertFalse(handler.finished_reading)
        handler.accept_body('2,')
        self.assertFalse(handler.finished_reading)
        handler.accept_body('3')
        handler.end_of_body()
        self.assertTrue(handler.finished_reading)
        self.assertEqual(('readv', ), handler.response.args)
        # co - nte - nt of a-file is the file contents we are extracting from.
        self.assertEqual('nte', handler.response.body)

    def test_readv_short_read_response_contents(self):
        """'readv' when a short read occurs sets the response appropriately."""
        self.build_tree(['a-file'])
        handler = self.build_handler(self.get_readonly_transport())
        handler.dispatch_command('readv', ('a-file', ))
        # read beyond the end of the file.
        handler.accept_body('100,1')
        handler.end_of_body()
        self.assertTrue(handler.finished_reading)
        self.assertEqual(('ShortReadvError', 'a-file', '100', '1', '0'),
            handler.response.args)
        self.assertEqual(None, handler.response.body)


class RemoteTransportRegistration(tests.TestCase):

    def test_registration(self):
        t = get_transport('bzr+ssh://example.com/path')
        self.assertIsInstance(t, remote.RemoteSSHTransport)
        self.assertEqual('example.com', t._host)

    def test_bzr_https(self):
        # https://bugs.launchpad.net/bzr/+bug/128456
        t = get_transport('bzr+https://example.com/path')
        self.assertIsInstance(t, remote.RemoteHTTPTransport)
        self.assertStartsWith(
            t._http_transport.base,
            'https://')


class TestRemoteTransport(tests.TestCase):
        
    def test_use_connection_factory(self):
        # We want to be able to pass a client as a parameter to RemoteTransport.
        input = StringIO("ok\n3\nbardone\n")
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        transport = remote.RemoteTransport(
            'bzr://localhost/', medium=client_medium)

        # We want to make sure the client is used when the first remote
        # method is called.  No data should have been sent, or read.
        self.assertEqual(0, input.tell())
        self.assertEqual('', output.getvalue())

        # Now call a method that should result in a single request : as the
        # transport makes its own protocol instances, we check on the wire.
        # XXX: TODO: give the transport a protocol factory, which can make
        # an instrumented protocol for us.
        self.assertEqual('bar', transport.get_bytes('foo'))
        # only the needed data should have been sent/received.
        self.assertEqual(13, input.tell())
        self.assertEqual('get\x01/foo\n', output.getvalue())

    def test__translate_error_readonly(self):
        """Sending a ReadOnlyError to _translate_error raises TransportNotPossible."""
        client_medium = medium.SmartClientMedium()
        transport = remote.RemoteTransport(
            'bzr://localhost/', medium=client_medium)
        self.assertRaises(errors.TransportNotPossible,
            transport._translate_error, ("ReadOnlyError", ))


class InstrumentedServerProtocol(medium.SmartServerStreamMedium):
    """A smart server which is backed by memory and saves its write requests."""

    def __init__(self, write_output_list):
        medium.SmartServerStreamMedium.__init__(self, memory.MemoryTransport())
        self._write_output_list = write_output_list


class TestSmartProtocol(tests.TestCase):
    """Base class for smart protocol tests.

    Each test case gets a smart_server and smart_client created during setUp().

    It is planned that the client can be called with self.call_client() giving
    it an expected server response, which will be fed into it when it tries to
    read. Likewise, self.call_server will call a servers method with a canned
    serialised client request. Output done by the client or server for these
    calls will be captured to self.to_server and self.to_client. Each element
    in the list is a write call from the client or server respectively.

    Subclasses can override client_protocol_class and server_protocol_class.
    """

    client_protocol_class = None
    server_protocol_class = None

    def setUp(self):
        super(TestSmartProtocol, self).setUp()
        # XXX: self.server_to_client doesn't seem to be used.  If so,
        # InstrumentedServerProtocol is redundant too.
        self.server_to_client = []
        self.to_server = StringIO()
        self.to_client = StringIO()
        self.client_medium = medium.SmartSimplePipesClientMedium(self.to_client,
            self.to_server)
        self.client_protocol = self.client_protocol_class(self.client_medium)
        self.smart_server = InstrumentedServerProtocol(self.server_to_client)
        self.smart_server_request = request.SmartServerRequestHandler(
            None, request.request_handlers)
        self.response_marker = getattr(
            self.client_protocol_class, 'response_marker', None)
        self.request_marker = getattr(
            self.client_protocol_class, 'request_marker', None)

    def assertOffsetSerialisation(self, expected_offsets, expected_serialised,
        client):
        """Check that smart (de)serialises offsets as expected.
        
        We check both serialisation and deserialisation at the same time
        to ensure that the round tripping cannot skew: both directions should
        be as expected.
        
        :param expected_offsets: a readv offset list.
        :param expected_seralised: an expected serial form of the offsets.
        """
        # XXX: '_deserialise_offsets' should be a method of the
        # SmartServerRequestProtocol in future.
        readv_cmd = vfs.ReadvRequest(None)
        offsets = readv_cmd._deserialise_offsets(expected_serialised)
        self.assertEqual(expected_offsets, offsets)
        serialised = client._serialise_offsets(offsets)
        self.assertEqual(expected_serialised, serialised)

    def build_protocol_waiting_for_body(self):
        out_stream = StringIO()
        smart_protocol = self.server_protocol_class(None, out_stream.write)
        smart_protocol.has_dispatched = True
        smart_protocol.request = self.smart_server_request
        class FakeCommand(object):
            def do_body(cmd, body_bytes):
                self.end_received = True
                self.assertEqual('abcdefg', body_bytes)
                return request.SuccessfulSmartServerResponse(('ok', ))
        smart_protocol.request._command = FakeCommand()
        # Call accept_bytes to make sure that internal state like _body_decoder
        # is initialised.  This test should probably be given a clearer
        # interface to work with that will not cause this inconsistency.
        #   -- Andrew Bennetts, 2006-09-28
        smart_protocol.accept_bytes('')
        return smart_protocol

    def assertServerToClientEncoding(self, expected_bytes, expected_tuple,
            input_tuples):
        """Assert that each input_tuple serialises as expected_bytes, and the
        bytes deserialise as expected_tuple.
        """
        # check the encoding of the server for all input_tuples matches
        # expected bytes
        for input_tuple in input_tuples:
            server_output = StringIO()
            server_protocol = self.server_protocol_class(
                None, server_output.write)
            server_protocol._send_response(
                _mod_request.SuccessfulSmartServerResponse(input_tuple))
            self.assertEqual(expected_bytes, server_output.getvalue())
        # check the decoding of the client smart_protocol from expected_bytes:
        input = StringIO(expected_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call('foo')
        self.assertEqual(expected_tuple, smart_protocol.read_response_tuple())


class CommonSmartProtocolTestMixin(object):

    def test_server_offset_serialisation(self):
        """The Smart protocol serialises offsets as a comma and \n string.

        We check a number of boundary cases are as expected: empty, one offset,
        one with the order of reads not increasing (an out of order read), and
        one that should coalesce.
        """
        self.assertOffsetSerialisation([], '', self.client_protocol)
        self.assertOffsetSerialisation([(1,2)], '1,2', self.client_protocol)
        self.assertOffsetSerialisation([(10,40), (0,5)], '10,40\n0,5',
            self.client_protocol)
        self.assertOffsetSerialisation([(1,2), (3,4), (100, 200)],
            '1,2\n3,4\n100,200', self.client_protocol)

    def test_errors_are_logged(self):
        """If an error occurs during testing, it is logged to the test log."""
        # XXX: should also test than an error inside a SmartServerRequest would
        # get logged.
        out_stream = StringIO()
        smart_protocol = self.server_protocol_class(None, out_stream.write)
        # This triggers a "bad request" error in all protocol versions.
        smart_protocol.accept_bytes('\0\0\0\0malformed request\n')
        test_log = self._get_log(keep_log_file=True)
        self.assertContainsRe(test_log, 'Traceback')
        self.assertContainsRe(test_log, 'SmartProtocolError')

    def test_connection_closed_reporting(self):
        input = StringIO()
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call('hello')
        ex = self.assertRaises(errors.ConnectionReset, 
            smart_protocol.read_response_tuple)
        self.assertEqual("Connection closed: "
            "please check connectivity and permissions "
            "(and try -Dhpss if further diagnosis is required)", str(ex))


class TestVersionOneFeaturesInProtocolOne(
    TestSmartProtocol, CommonSmartProtocolTestMixin):
    """Tests for version one smart protocol features as implemeted by version
    one."""

    client_protocol_class = protocol.SmartClientRequestProtocolOne
    server_protocol_class = protocol.SmartServerRequestProtocolOne

    def test_construct_version_one_server_protocol(self):
        smart_protocol = protocol.SmartServerRequestProtocolOne(None, None)
        self.assertEqual('', smart_protocol.excess_buffer)
        self.assertEqual('', smart_protocol.in_buffer)
        self.assertFalse(smart_protocol.has_dispatched)
        self.assertEqual(1, smart_protocol.next_read_size())

    def test_construct_version_one_client_protocol(self):
        # we can construct a client protocol from a client medium request
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        request = client_medium.get_request()
        client_protocol = protocol.SmartClientRequestProtocolOne(request)

    def test_accept_bytes_of_bad_request_to_protocol(self):
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            None, out_stream.write)
        smart_protocol.accept_bytes('abc')
        self.assertEqual('abc', smart_protocol.in_buffer)
        smart_protocol.accept_bytes('\n')
        self.assertEqual(
            "error\x01Generic bzr smart protocol error: bad request 'abc'\n",
            out_stream.getvalue())
        self.assertTrue(smart_protocol.has_dispatched)
        self.assertEqual(0, smart_protocol.next_read_size())

    def test_accept_body_bytes_to_protocol(self):
        protocol = self.build_protocol_waiting_for_body()
        self.assertEqual(6, protocol.next_read_size())
        protocol.accept_bytes('7\nabc')
        self.assertEqual(9, protocol.next_read_size())
        protocol.accept_bytes('defgd')
        protocol.accept_bytes('one\n')
        self.assertEqual(0, protocol.next_read_size())
        self.assertTrue(self.end_received)

    def test_accept_request_and_body_all_at_once(self):
        self._captureVar('BZR_NO_SMART_VFS', None)
        mem_transport = memory.MemoryTransport()
        mem_transport.put_bytes('foo', 'abcdefghij')
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(mem_transport,
                out_stream.write)
        smart_protocol.accept_bytes('readv\x01foo\n3\n3,3done\n')
        self.assertEqual(0, smart_protocol.next_read_size())
        self.assertEqual('readv\n3\ndefdone\n', out_stream.getvalue())
        self.assertEqual('', smart_protocol.excess_buffer)
        self.assertEqual('', smart_protocol.in_buffer)

    def test_accept_excess_bytes_are_preserved(self):
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            None, out_stream.write)
        smart_protocol.accept_bytes('hello\nhello\n')
        self.assertEqual("ok\x013\n", out_stream.getvalue())
        self.assertEqual("hello\n", smart_protocol.excess_buffer)
        self.assertEqual("", smart_protocol.in_buffer)

    def test_accept_excess_bytes_after_body(self):
        protocol = self.build_protocol_waiting_for_body()
        protocol.accept_bytes('7\nabcdefgdone\nX')
        self.assertTrue(self.end_received)
        self.assertEqual("X", protocol.excess_buffer)
        self.assertEqual("", protocol.in_buffer)
        protocol.accept_bytes('Y')
        self.assertEqual("XY", protocol.excess_buffer)
        self.assertEqual("", protocol.in_buffer)

    def test_accept_excess_bytes_after_dispatch(self):
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            None, out_stream.write)
        smart_protocol.accept_bytes('hello\n')
        self.assertEqual("ok\x013\n", out_stream.getvalue())
        smart_protocol.accept_bytes('hel')
        self.assertEqual("hel", smart_protocol.excess_buffer)
        smart_protocol.accept_bytes('lo\n')
        self.assertEqual("hello\n", smart_protocol.excess_buffer)
        self.assertEqual("", smart_protocol.in_buffer)

    def test__send_response_sets_finished_reading(self):
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            None, lambda x: None)
        self.assertEqual(1, smart_protocol.next_read_size())
        smart_protocol._send_response(
            request.SuccessfulSmartServerResponse(('x',)))
        self.assertEqual(0, smart_protocol.next_read_size())

    def test__send_response_errors_with_base_response(self):
        """Ensure that only the Successful/Failed subclasses are used."""
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            None, lambda x: None)
        self.assertRaises(AttributeError, smart_protocol._send_response,
            request.SmartServerResponse(('x',)))

    def test_query_version(self):
        """query_version on a SmartClientProtocolOne should return a number.
        
        The protocol provides the query_version because the domain level clients
        may all need to be able to probe for capabilities.
        """
        # What we really want to test here is that SmartClientProtocolOne calls
        # accept_bytes(tuple_based_encoding_of_hello) and reads and parses the
        # response of tuple-encoded (ok, 1).  Also, seperately we should test
        # the error if the response is a non-understood version.
        input = StringIO('ok\x013\n')
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        self.assertEqual(3, smart_protocol.query_version())

    def test_client_call_empty_response(self):
        # protocol.call() can get back an empty tuple as a response. This occurs
        # when the parsed line is an empty line, and results in a tuple with
        # one element - an empty string.
        self.assertServerToClientEncoding('\n', ('', ), [(), ('', )])

    def test_client_call_three_element_response(self):
        # protocol.call() can get back tuples of other lengths. A three element
        # tuple should be unpacked as three strings.
        self.assertServerToClientEncoding('a\x01b\x0134\n', ('a', 'b', '34'),
            [('a', 'b', '34')])

    def test_client_call_with_body_bytes_uploads(self):
        # protocol.call_with_body_bytes should length-prefix the bytes onto the
        # wire.
        expected_bytes = "foo\n7\nabcdefgdone\n"
        input = StringIO("\n")
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call_with_body_bytes(('foo', ), "abcdefg")
        self.assertEqual(expected_bytes, output.getvalue())

    def test_client_call_with_body_readv_array(self):
        # protocol.call_with_upload should encode the readv array and then
        # length-prefix the bytes onto the wire.
        expected_bytes = "foo\n7\n1,2\n5,6done\n"
        input = StringIO("\n")
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call_with_body_readv_array(('foo', ), [(1,2),(5,6)])
        self.assertEqual(expected_bytes, output.getvalue())

    def test_client_read_body_bytes_all(self):
        # read_body_bytes should decode the body bytes from the wire into
        # a response.
        expected_bytes = "1234567"
        server_bytes = "ok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        self.assertEqual(expected_bytes, smart_protocol.read_body_bytes())

    def test_client_read_body_bytes_incremental(self):
        # test reading a few bytes at a time from the body
        # XXX: possibly we should test dribbling the bytes into the stringio
        # to make the state machine work harder: however, as we use the
        # LengthPrefixedBodyDecoder that is already well tested - we can skip
        # that.
        expected_bytes = "1234567"
        server_bytes = "ok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        self.assertEqual(expected_bytes[0:2], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[2:4], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[4:6], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[6], smart_protocol.read_body_bytes())

    def test_client_cancel_read_body_does_not_eat_body_bytes(self):
        # cancelling the expected body needs to finish the request, but not
        # read any more bytes.
        expected_bytes = "1234567"
        server_bytes = "ok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        smart_protocol.cancel_read_body()
        self.assertEqual(3, input.tell())
        self.assertRaises(
            errors.ReadingCompleted, smart_protocol.read_body_bytes)


class TestVersionOneFeaturesInProtocolTwo(
    TestSmartProtocol, CommonSmartProtocolTestMixin):
    """Tests for version one smart protocol features as implemeted by version
    two.
    """

    client_protocol_class = protocol.SmartClientRequestProtocolTwo
    server_protocol_class = protocol.SmartServerRequestProtocolTwo

    def test_construct_version_two_server_protocol(self):
        smart_protocol = protocol.SmartServerRequestProtocolTwo(None, None)
        self.assertEqual('', smart_protocol.excess_buffer)
        self.assertEqual('', smart_protocol.in_buffer)
        self.assertFalse(smart_protocol.has_dispatched)
        self.assertEqual(1, smart_protocol.next_read_size())

    def test_construct_version_two_client_protocol(self):
        # we can construct a client protocol from a client medium request
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        request = client_medium.get_request()
        client_protocol = protocol.SmartClientRequestProtocolTwo(request)

    def test_accept_bytes_of_bad_request_to_protocol(self):
        out_stream = StringIO()
        smart_protocol = self.server_protocol_class(None, out_stream.write)
        smart_protocol.accept_bytes('abc')
        self.assertEqual('abc', smart_protocol.in_buffer)
        smart_protocol.accept_bytes('\n')
        self.assertEqual(
            self.response_marker +
            "failed\nerror\x01Generic bzr smart protocol error: bad request 'abc'\n",
            out_stream.getvalue())
        self.assertTrue(smart_protocol.has_dispatched)
        self.assertEqual(0, smart_protocol.next_read_size())

    def test_accept_body_bytes_to_protocol(self):
        protocol = self.build_protocol_waiting_for_body()
        self.assertEqual(6, protocol.next_read_size())
        protocol.accept_bytes('7\nabc')
        self.assertEqual(9, protocol.next_read_size())
        protocol.accept_bytes('defgd')
        protocol.accept_bytes('one\n')
        self.assertEqual(0, protocol.next_read_size())
        self.assertTrue(self.end_received)

    def test_accept_request_and_body_all_at_once(self):
        self._captureVar('BZR_NO_SMART_VFS', None)
        mem_transport = memory.MemoryTransport()
        mem_transport.put_bytes('foo', 'abcdefghij')
        out_stream = StringIO()
        smart_protocol = self.server_protocol_class(
            mem_transport, out_stream.write)
        smart_protocol.accept_bytes('readv\x01foo\n3\n3,3done\n')
        self.assertEqual(0, smart_protocol.next_read_size())
        self.assertEqual(self.response_marker +
                         'success\nreadv\n3\ndefdone\n',
                         out_stream.getvalue())
        self.assertEqual('', smart_protocol.excess_buffer)
        self.assertEqual('', smart_protocol.in_buffer)

    def test_accept_excess_bytes_are_preserved(self):
        out_stream = StringIO()
        smart_protocol = self.server_protocol_class(None, out_stream.write)
        smart_protocol.accept_bytes('hello\nhello\n')
        self.assertEqual(self.response_marker + "success\nok\x013\n",
                         out_stream.getvalue())
        self.assertEqual("hello\n", smart_protocol.excess_buffer)
        self.assertEqual("", smart_protocol.in_buffer)

    def test_accept_excess_bytes_after_body(self):
        # The excess bytes look like the start of another request.
        server_protocol = self.build_protocol_waiting_for_body()
        server_protocol.accept_bytes('7\nabcdefgdone\n' + self.response_marker)
        self.assertTrue(self.end_received)
        self.assertEqual(self.response_marker,
                         server_protocol.excess_buffer)
        self.assertEqual("", server_protocol.in_buffer)
        server_protocol.accept_bytes('Y')
        self.assertEqual(self.response_marker + "Y",
                         server_protocol.excess_buffer)
        self.assertEqual("", server_protocol.in_buffer)

    def test_accept_excess_bytes_after_dispatch(self):
        out_stream = StringIO()
        smart_protocol = self.server_protocol_class(None, out_stream.write)
        smart_protocol.accept_bytes('hello\n')
        self.assertEqual(self.response_marker + "success\nok\x013\n",
                         out_stream.getvalue())
        smart_protocol.accept_bytes(self.request_marker + 'hel')
        self.assertEqual(self.request_marker + "hel",
                         smart_protocol.excess_buffer)
        smart_protocol.accept_bytes('lo\n')
        self.assertEqual(self.request_marker + "hello\n",
                         smart_protocol.excess_buffer)
        self.assertEqual("", smart_protocol.in_buffer)

    def test__send_response_sets_finished_reading(self):
        smart_protocol = self.server_protocol_class(None, lambda x: None)
        self.assertEqual(1, smart_protocol.next_read_size())
        smart_protocol._send_response(
            request.SuccessfulSmartServerResponse(('x',)))
        self.assertEqual(0, smart_protocol.next_read_size())

    def test__send_response_errors_with_base_response(self):
        """Ensure that only the Successful/Failed subclasses are used."""
        smart_protocol = self.server_protocol_class(None, lambda x: None)
        self.assertRaises(AttributeError, smart_protocol._send_response,
            request.SmartServerResponse(('x',)))

    def test_query_version(self):
        """query_version on a SmartClientProtocolTwo should return a number.
        
        The protocol provides the query_version because the domain level clients
        may all need to be able to probe for capabilities.
        """
        # What we really want to test here is that SmartClientProtocolTwo calls
        # accept_bytes(tuple_based_encoding_of_hello) and reads and parses the
        # response of tuple-encoded (ok, 1).  Also, seperately we should test
        # the error if the response is a non-understood version.
        input = StringIO(self.response_marker + 'success\nok\x013\n')
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        self.assertEqual(3, smart_protocol.query_version())

    def test_client_call_empty_response(self):
        # protocol.call() can get back an empty tuple as a response. This occurs
        # when the parsed line is an empty line, and results in a tuple with
        # one element - an empty string.
        self.assertServerToClientEncoding(
            self.response_marker + 'success\n\n', ('', ), [(), ('', )])

    def test_client_call_three_element_response(self):
        # protocol.call() can get back tuples of other lengths. A three element
        # tuple should be unpacked as three strings.
        self.assertServerToClientEncoding(
            self.response_marker + 'success\na\x01b\x0134\n',
            ('a', 'b', '34'),
            [('a', 'b', '34')])

    def test_client_call_with_body_bytes_uploads(self):
        # protocol.call_with_body_bytes should length-prefix the bytes onto the
        # wire.
        expected_bytes = self.request_marker + "foo\n7\nabcdefgdone\n"
        input = StringIO("\n")
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call_with_body_bytes(('foo', ), "abcdefg")
        self.assertEqual(expected_bytes, output.getvalue())

    def test_client_call_with_body_readv_array(self):
        # protocol.call_with_upload should encode the readv array and then
        # length-prefix the bytes onto the wire.
        expected_bytes = self.request_marker + "foo\n7\n1,2\n5,6done\n"
        input = StringIO("\n")
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call_with_body_readv_array(('foo', ), [(1,2),(5,6)])
        self.assertEqual(expected_bytes, output.getvalue())

    def test_client_read_body_bytes_all(self):
        # read_body_bytes should decode the body bytes from the wire into
        # a response.
        expected_bytes = "1234567"
        server_bytes = (self.response_marker +
                        "success\nok\n7\n1234567done\n")
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        self.assertEqual(expected_bytes, smart_protocol.read_body_bytes())

    def test_client_read_body_bytes_incremental(self):
        # test reading a few bytes at a time from the body
        # XXX: possibly we should test dribbling the bytes into the stringio
        # to make the state machine work harder: however, as we use the
        # LengthPrefixedBodyDecoder that is already well tested - we can skip
        # that.
        expected_bytes = "1234567"
        server_bytes = self.response_marker + "success\nok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        self.assertEqual(expected_bytes[0:2], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[2:4], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[4:6], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[6], smart_protocol.read_body_bytes())

    def test_client_cancel_read_body_does_not_eat_body_bytes(self):
        # cancelling the expected body needs to finish the request, but not
        # read any more bytes.
        server_bytes = self.response_marker + "success\nok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        smart_protocol.cancel_read_body()
        self.assertEqual(len(self.response_marker + 'success\nok\n'),
                         input.tell())
        self.assertRaises(
            errors.ReadingCompleted, smart_protocol.read_body_bytes)


class TestSmartProtocolTwoSpecificsMixin(object):

    def assertBodyStreamSerialisation(self, expected_serialisation,
                                      body_stream):
        """Assert that body_stream is serialised as expected_serialisation."""
        out_stream = StringIO()
        protocol._send_stream(body_stream, out_stream.write)
        self.assertEqual(expected_serialisation, out_stream.getvalue())

    def assertBodyStreamRoundTrips(self, body_stream):
        """Assert that body_stream is the same after being serialised and
        deserialised.
        """
        out_stream = StringIO()
        protocol._send_stream(body_stream, out_stream.write)
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes(out_stream.getvalue())
        decoded_stream = list(iter(decoder.read_next_chunk, None))
        self.assertEqual(body_stream, decoded_stream)

    def test_body_stream_serialisation_empty(self):
        """A body_stream with no bytes can be serialised."""
        self.assertBodyStreamSerialisation('chunked\nEND\n', [])
        self.assertBodyStreamRoundTrips([])

    def test_body_stream_serialisation(self):
        stream = ['chunk one', 'chunk two', 'chunk three']
        self.assertBodyStreamSerialisation(
            'chunked\n' + '9\nchunk one' + '9\nchunk two' + 'b\nchunk three' +
            'END\n',
            stream)
        self.assertBodyStreamRoundTrips(stream)

    def test_body_stream_with_empty_element_serialisation(self):
        """A body stream can include ''.

        The empty string can be transmitted like any other string.
        """
        stream = ['', 'chunk']
        self.assertBodyStreamSerialisation(
            'chunked\n' + '0\n' + '5\nchunk' + 'END\n', stream)
        self.assertBodyStreamRoundTrips(stream)

    def test_body_stream_error_serialistion(self):
        stream = ['first chunk',
                  request.FailedSmartServerResponse(
                      ('FailureName', 'failure arg'))]
        expected_bytes = (
            'chunked\n' + 'b\nfirst chunk' +
            'ERR\n' + 'b\nFailureName' + 'b\nfailure arg' +
            'END\n')
        self.assertBodyStreamSerialisation(expected_bytes, stream)
        self.assertBodyStreamRoundTrips(stream)

    def test__send_response_includes_failure_marker(self):
        """FailedSmartServerResponse have 'failed\n' after the version."""
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolTwo(
            None, out_stream.write)
        smart_protocol._send_response(
            request.FailedSmartServerResponse(('x',)))
        self.assertEqual(protocol.RESPONSE_VERSION_TWO + 'failed\nx\n',
                         out_stream.getvalue())

    def test__send_response_includes_success_marker(self):
        """SuccessfulSmartServerResponse have 'success\n' after the version."""
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolTwo(
            None, out_stream.write)
        smart_protocol._send_response(
            request.SuccessfulSmartServerResponse(('x',)))
        self.assertEqual(protocol.RESPONSE_VERSION_TWO + 'success\nx\n',
                         out_stream.getvalue())

    def test__send_response_with_body_stream_sets_finished_reading(self):
        smart_protocol = protocol.SmartServerRequestProtocolTwo(
            None, lambda x: None)
        self.assertEqual(1, smart_protocol.next_read_size())
        smart_protocol._send_response(
            request.SuccessfulSmartServerResponse(('x',), body_stream=[]))
        self.assertEqual(0, smart_protocol.next_read_size())

    def test_streamed_body_bytes(self):
        body_header = 'chunked\n'
        two_body_chunks = "4\n1234" + "3\n567"
        body_terminator = "END\n"
        server_bytes = (protocol.RESPONSE_VERSION_TWO +
                        "success\nok\n" + body_header + two_body_chunks +
                        body_terminator)
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        stream = smart_protocol.read_streamed_body()
        self.assertEqual(['1234', '567'], list(stream))

    def test_read_streamed_body_error(self):
        """When a stream is interrupted by an error..."""
        body_header = 'chunked\n'
        a_body_chunk = '4\naaaa'
        err_signal = 'ERR\n'
        err_chunks = 'a\nerror arg1' + '4\narg2'
        finish = 'END\n'
        body = body_header + a_body_chunk + err_signal + err_chunks + finish
        server_bytes = (protocol.RESPONSE_VERSION_TWO +
                        "success\nok\n" + body)
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        smart_request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(smart_request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        expected_chunks = [
            'aaaa',
            request.FailedSmartServerResponse(('error arg1', 'arg2'))]
        stream = smart_protocol.read_streamed_body()
        self.assertEqual(expected_chunks, list(stream))

    def test_client_read_response_tuple_sets_response_status(self):
        server_bytes = protocol.RESPONSE_VERSION_TWO + "success\nok\n"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(False)
        self.assertEqual(True, smart_protocol.response_status)


class TestSmartProtocolTwoSpecifics(
        TestSmartProtocol, TestSmartProtocolTwoSpecificsMixin):
    """Tests for aspects of smart protocol version two that are unique to
    version two.

    Thus tests involving body streams and success/failure markers belong here.
    """

    client_protocol_class = protocol.SmartClientRequestProtocolTwo
    server_protocol_class = protocol.SmartServerRequestProtocolTwo


class TestVersionOneFeaturesInProtocolThree(
    TestSmartProtocol, CommonSmartProtocolTestMixin):
    """Tests for version one smart protocol features as implemented by version
    three.
    """

    client_protocol_class = protocol.SmartClientRequestProtocolThree
    # build_server_protocol_three is a function, so we can't set it as a class
    # attribute directly, because then Python will assume it is actually a
    # method.  So we make server_protocol_class be a static method, rather than
    # simply doing:
    # "server_protocol_class = protocol.build_server_protocol_three".
    server_protocol_class = staticmethod(protocol.build_server_protocol_three)

    def test_construct_version_three_server_protocol(self):
        smart_protocol = protocol.ProtocolThreeDecoder(None)
        self.assertEqual('', smart_protocol.excess_buffer)
        self.assertEqual('', smart_protocol._in_buffer)
        self.assertFalse(smart_protocol.has_dispatched)
        # The protocol starts by expecting four bytes, a length prefix for the
        # headers.
        self.assertEqual(4, smart_protocol.next_read_size())


class NoOpRequest(request.SmartServerRequest):

    def do(self):
        return request.SuccessfulSmartServerResponse(())

dummy_registry = {'ARG': NoOpRequest}


class LoggingMessageHandler(object):

    def __init__(self):
        self.event_log = []

    def _log(self, *args):
        self.event_log.append(args)

    def headers_received(self, headers):
        self._log('headers', headers)

    def protocol_error(self, exception):
        self._log('protocol_error', exception)

    def byte_part_received(self, byte):
        self._log('byte', byte)

    def bytes_part_received(self, bytes):
        self._log('bytes', bytes)

    def structure_part_received(self, structure):
        self._log('structure', structure)

    def end_received(self):
        self._log('end')


class TestProtocolThree(TestSmartProtocol):
    """Tests for v3 of the server-side protocol."""

    client_protocol_class = protocol.SmartClientRequestProtocolThree
    server_protocol_class = protocol.ProtocolThreeDecoder

    def test_trivial_request(self):
        """Smoke test for the simplest possible v3 request: empty headers, no
        message parts.
        """
        output = StringIO()
        headers = '\0\0\0\x02de'  # length-prefixed, bencoded empty dict
        end = 'e'
        request_bytes = headers + end
        smart_protocol = self.server_protocol_class(LoggingMessageHandler())
        smart_protocol.accept_bytes(request_bytes)
        self.assertEqual(0, smart_protocol.next_read_size())
        self.assertEqual('', smart_protocol.excess_buffer)

    # XXX: TestMessagePartDecoding vvv XXX
    def make_protocol_expecting_message_part(self):
        headers = '\0\0\0\x02de'  # length-prefixed, bencoded empty dict
        message_handler = LoggingMessageHandler()
        smart_protocol = self.server_protocol_class(message_handler)
        smart_protocol.accept_bytes(headers)
        # Clear the event log
        del message_handler.event_log[:]
        return smart_protocol, message_handler.event_log

    def test_decode_one_byte(self):
        """The protocol can decode a 'one byte' message part."""
        smart_protocol, event_log = self.make_protocol_expecting_message_part()
        smart_protocol.accept_bytes('ox')
        self.assertEqual([('byte', 'x')], event_log)

    def test_decode_bytes(self):
        """The protocol can decode a 'bytes' message part."""
        smart_protocol, event_log = self.make_protocol_expecting_message_part()
        smart_protocol.accept_bytes(
            'b' # message part kind
            '\0\0\0\x07' # length prefix
            'payload' # payload
            )
        self.assertEqual([('bytes', 'payload')], event_log)

    def test_decode_structure(self):
        """The protocol can decode a 'structure' message part."""
        smart_protocol, event_log = self.make_protocol_expecting_message_part()
        smart_protocol.accept_bytes(
            's' # message part kind
            '\0\0\0\x07' # length prefix
            'l3:ARGe' # ['ARG']
            )
        self.assertEqual([('structure', ['ARG'])], event_log)

    def test_decode_multiple_bytes(self):
        """The protocol can decode a multiple 'bytes' message parts."""
        smart_protocol, event_log = self.make_protocol_expecting_message_part()
        smart_protocol.accept_bytes(
            'b' # message part kind
            '\0\0\0\x05' # length prefix
            'first' # payload
            'b' # message part kind
            '\0\0\0\x06'
            'second'
            )
        self.assertEqual(
            [('bytes', 'first'), ('bytes', 'second')], event_log)

    # XXX: TestMessagePartDecoding ^^^ XXX

#    def make_protocol_expecting_body(self):
#        """Returns a SmartServerRequestProtocolThree instance in the
#        'expecting_body_kind' state.
#
#        That is, return a protocol object that is waiting to receive a body.
#        """
#        output = StringIO()
#        headers = '\0\0\0\x02de'  # length-prefixed, bencoded empty dict
#        args = '\0\0\0\x07l3:ARGe' # length-prefixed, bencoded list: ['ARG']
#        request_bytes = headers + args
#        smart_protocol = self.server_protocol_class(None, output.write,
#            dummy_registry)
#        smart_protocol.accept_bytes(request_bytes)
#        return smart_protocol
#
#    def assertBodyParsingBehaviour(self, calls, protocol_bytes):
#        """Assert that the given bytes cause an exact sequence of calls to the
#        request handler, followed by an end_received call.
#        """
#        calls = calls + [('end_received',)]
#        smart_protocol = self.make_protocol_expecting_body()
#        smart_protocol.request_handler = InstrumentedRequestHandler()
#        smart_protocol.accept_bytes(protocol_bytes)
#        self.assertEqual(calls, smart_protocol.request_handler.calls,
#            "%r was not parsed as expected" % (protocol_bytes,))
#
#    def test_request_no_body(self):
#        """Parsing a request with no body calls no_body_received on the request
#        handler.
#        """
#        body = (
#            'n' # body kind
#            )
#        self.assertBodyParsingBehaviour([('no_body_received',)], body)
#
#    def test_request_prefixed_body(self):
#        """Parsing a request with a length-prefixed body calls
#        prefixed_body_received on the request handler.
#        """
#        body = (
#            'p' # body kind
#            '\0\0\0\x07' # length prefix
#            'content' # the payload
#            )
#        self.assertBodyParsingBehaviour(
#            [('prefixed_body_received', 'content')], body)
#
#    def test_request_chunked_body_zero_chunks(self):
#        """Parsing a request with a streamed body with no chunks does not call
#        the request handler!
#        """
#        body = (
#            's' # body kind
#            't' # stream terminator
#            )
#        self.assertBodyParsingBehaviour([], body)
#
#    def test_request_chunked_body_one_chunks(self):
#        """Parsing a request with a streamed body with one chunk calls
#        body_chunk_received once.
#        """
#        body = (
#            's' # body kind
#            'c' # chunk indicator
#            '\0\0\0\x03' # chunk length
#            'one' # chunk content
#            # Done
#            't' # stream terminator
#            )
#        self.assertBodyParsingBehaviour([('body_chunk_received', 'one')], body)
#
#    def test_request_chunked_body_two_chunks(self):
#        """Parsing a request with a streamed body with multiple chunks calls
#        body_chunk_received for each chunk.
#        """
#        body = (
#            's' # body kind
#            # First chunk
#            'c' # chunk indicator
#            '\0\0\0\x03' # chunk length
#            'one' # chunk content
#            # Second chunk
#            'c'
#            '\0\0\0\x03'
#            'two'
#            # Done
#            't' # stream terminator
#            )
#        self.assertBodyParsingBehaviour(
#            [('body_chunk_received', 'one'), ('body_chunk_received', 'two')],
#            body)


class TestConventionalResponseHandler(tests.TestCase):

    def test_interrupted_body_stream(self):
        interrupted_body_stream = (
            'oS' # successful response
            's\0\0\0\x02le' # empty args
            'b\0\0\0\x09chunk one' # first chunk
            'b\0\0\0\x09chunk two' # second chunk
            'oE' # error flag
            's\0\0\0\x0el5:error3:abce' # bencoded error
            'e' # message end
            )
        from bzrlib.smart.message import ConventionalResponseHandler
        response_handler = ConventionalResponseHandler()
        protocol_decoder = protocol.ProtocolThreeDecoder(response_handler)
        # put decoder in desired state (waiting for message parts)
        protocol_decoder.state_accept = protocol_decoder._state_accept_expecting_message_part
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            StringIO(interrupted_body_stream), output)
        medium_request = client_medium.get_request()
        medium_request.finished_writing()
        response_handler.setProtoAndMedium(protocol_decoder, medium_request)
        stream = response_handler.read_streamed_body()
        self.assertEqual('chunk one', stream.next())
        self.assertEqual('chunk two', stream.next())
        exc = self.assertRaises(errors.ErrorFromSmartServer, stream.next)
        self.assertEqual(('error', 'abc'), exc.error_tuple)


class InstrumentedRequestHandler(object):
    """Test Double of SmartServerRequestHandler."""

    def __init__(self):
        self.calls = []

    def body_chunk_received(self, chunk_bytes):
        self.calls.append(('body_chunk_received', chunk_bytes))

    def no_body_received(self):
        self.calls.append(('no_body_received',))

    def prefixed_body_received(self, body_bytes):
        self.calls.append(('prefixed_body_received', body_bytes))

    def end_received(self):
        self.calls.append(('end_received',))


#class TestClientDecodingProtocolThree(TestSmartProtocol):
#    """Tests for v3 of the client-side protocol decoding."""
#
#    client_protocol_class = protocol.SmartClientRequestProtocolThree
#    server_protocol_class = protocol.SmartServerRequestProtocolThree
#
#    def test_trivial_response_decoding(self):
#        """Smoke test for the simplest possible v3 response: no headers, no
#        body, no args.
#        """
#        output = StringIO()
#        headers = '\0\0\0\x02de'  # length-prefixed, bencoded empty dict
#        body = 'n'
#        response_status = 'S' # success
#        args = '\0\0\0\x02le' # length-prefixed, bencoded empty list
#        request_bytes = headers + body + response_status + args
#        smart_protocol = self.client_protocol_class(None)
#        smart_protocol.accept_bytes(request_bytes)
#        self.assertEqual(0, smart_protocol.next_read_size())
#        self.assertEqual('', smart_protocol.excess_buffer)
#        self.assertEqual('', smart_protocol.unused_data)


class TestClientEncodingProtocolThree(TestSmartProtocol):

    client_protocol_class = protocol.SmartClientRequestProtocolThree
    server_protocol_class = protocol.ProtocolThreeDecoder

    def make_client_encoder_and_output(self):
        input = None
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        return smart_protocol, output

    def test_call_smoke_test(self):
        """A smoke test SmartClientRequestProtocolThree.call.

        This test checks that a particular simple invocation of call emits the
        correct bytes for that invocation.
        """
        smart_protocol, output = self.make_client_encoder_and_output()
        smart_protocol.call('one arg', headers={'header name': 'header value'})
        self.assertEquals(
            'bzr message 3 (bzr 1.3)\n' # protocol version
            '\x00\x00\x00\x1fd11:header name12:header valuee' # headers
            's\x00\x00\x00\x0bl7:one arge' # args
            'e', # end
            output.getvalue())

    def test_call_default_headers(self):
        """SmartClientRequestProtocolThree.call by default sends a 'Software
        version' header.
        """
        smart_protocol, output = self.make_client_encoder_and_output()
        smart_protocol.call('foo')
        # XXX: using assertContainsRe is a pretty poor way to assert this.
        self.assertContainsRe(output.getvalue(), 'Software version')
        
    def test_call_with_body_bytes_smoke_test(self):
        """A smoke test SmartClientRequestProtocolThree.call_with_body_bytes.

        This test checks that a particular simple invocation of
        call_with_body_bytes emits the correct bytes for that invocation.
        """
        smart_protocol, output = self.make_client_encoder_and_output()
        smart_protocol.call_with_body_bytes(
            ('one arg',), 'body bytes',
            headers={'header name': 'header value'})
        self.assertEquals(
            'bzr message 3 (bzr 1.3)\n' # protocol version
            '\x00\x00\x00\x1fd11:header name12:header valuee' # headers
            's\x00\x00\x00\x0bl7:one arge' # args
            'b' # there is a prefixed body
            '\x00\x00\x00\nbody bytes' # the prefixed body
            'e', # end
            output.getvalue())


#class TestProtocolTestCoverage(tests.TestCase):
#
#    def assertSetEqual(self, set_a, set_b):
#        if set_a != set_b:
#            missing_from_a = sorted(set_b - set_a)
#            missing_from_b = sorted(set_a - set_b)
#            raise self.failureException(
#                'Sets not equal.\na is missing: %r\nb is missing: %r'
#                % (missing_from_a, missing_from_b))
#
#    def get_tests_from_classes(self, test_case_classes):
#        loader = unittest.TestLoader()
#        test_names = []
#        for test_case_class in test_case_classes:
#            names = loader.getTestCaseNames(test_case_class)
#            test_names.extend(names)
#        return set(self.remove_version_specific_tests(test_names))
#
#    def remove_version_specific_tests(self, test_names):
#        return [name for name in test_names
#                if not name.startswith('test_construct_version_')]
#    
#    def test_ensure_consistent_coverage(self):
#        """We should be testing the same set of conditions for all protocol
#        implementations.
#
#        The implementations of those tests may differ (so we can't use simple
#        test parameterisation to keep the tests synchronised), so this test is
#        to ensure that all tests for v1 are done for v2 and v3, and that all v2
#        tests are done for v3.
#        """
#        v1_classes = [TestVersionOneFeaturesInProtocolOne]
#        v2_classes = [
#            TestVersionOneFeaturesInProtocolTwo,
#            TestVersionTwoFeaturesInProtocolTwo]
##        v3_classes = [
##            TestVersionOneFeaturesInProtocolThree,
##            TestVersionTwoFeaturesInProtocolThree,
##            TestVersionThreeFeaturesInProtocolThree]
#
#        # v2 implements all of v1
#        protocol1_tests = self.get_tests_from_classes(v1_classes)
#        protocol2_basic_tests = self.get_tests_from_class(
#            TestVersionOneFeaturesInProtocolTwo)
#        self.assertSetEqual(protocol1_tests, protocol2_basic_tests)
#
#        # v3 implements all of v1 and v2.
#        protocol2_tests = self.get_tests_from_classes(v2_classes)
#        protocol3_basic_tests = self.get_tests_from_class(
#            TestVersionOneFeaturesInProtocolThree)
#        self.assertSetEqual(protocol2_tests, protocol3_basic_tests)


class TestSmartClientUnicode(tests.TestCase):
    """_SmartClient tests for unicode arguments.

    Unicode arguments to call_with_body_bytes are not correct (remote method
    names, arguments, and bodies must all be expressed as byte strings), but
    _SmartClient should gracefully reject them, rather than getting into a
    broken state that prevents future correct calls from working.  That is, it
    should be possible to issue more requests on the medium afterwards, rather
    than allowing one bad call to call_with_body_bytes to cause later calls to
    mysteriously fail with TooManyConcurrentRequests.
    """

    def assertCallDoesNotBreakMedium(self, method, args, body):
        """Call a medium with the given method, args and body, then assert that
        the medium is left in a sane state, i.e. is capable of allowing further
        requests.
        """
        input = StringIO("\n")
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        smart_client = client._SmartClient(client_medium)
        self.assertRaises(TypeError,
            smart_client.call_with_body_bytes, method, args, body)
        self.assertEqual("", output.getvalue())
        self.assertEqual(None, client_medium._current_request)

    def test_call_with_body_bytes_unicode_method(self):
        self.assertCallDoesNotBreakMedium(u'method', ('args',), 'body')

    def test_call_with_body_bytes_unicode_args(self):
        self.assertCallDoesNotBreakMedium('method', (u'args',), 'body')
        self.assertCallDoesNotBreakMedium('method', ('arg1', u'arg2'), 'body')

    def test_call_with_body_bytes_unicode_body(self):
        self.assertCallDoesNotBreakMedium('method', ('args',), u'body')


class LengthPrefixedBodyDecoder(tests.TestCase):

    # XXX: TODO: make accept_reading_trailer invoke translate_response or 
    # something similar to the ProtocolBase method.

    def test_construct(self):
        decoder = protocol.LengthPrefixedBodyDecoder()
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(6, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)

    def test_accept_bytes(self):
        decoder = protocol.LengthPrefixedBodyDecoder()
        decoder.accept_bytes('')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(6, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('7')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(6, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('\na')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(11, decoder.next_read_size())
        self.assertEqual('a', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('bcdefgd')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(4, decoder.next_read_size())
        self.assertEqual('bcdefg', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('one')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('\nblarg')
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('blarg', decoder.unused_data)
        
    def test_accept_bytes_all_at_once_with_excess(self):
        decoder = protocol.LengthPrefixedBodyDecoder()
        decoder.accept_bytes('1\nadone\nunused')
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual('a', decoder.read_pending_data())
        self.assertEqual('unused', decoder.unused_data)

    def test_accept_bytes_exact_end_of_body(self):
        decoder = protocol.LengthPrefixedBodyDecoder()
        decoder.accept_bytes('1\na')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(5, decoder.next_read_size())
        self.assertEqual('a', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('done\n')
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)


class TestChunkedBodyDecoder(tests.TestCase):
    """Tests for ChunkedBodyDecoder.
    
    This is the body decoder used for protocol version two.
    """

    def test_construct(self):
        decoder = protocol.ChunkedBodyDecoder()
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(8, decoder.next_read_size())
        self.assertEqual(None, decoder.read_next_chunk())
        self.assertEqual('', decoder.unused_data)

    def test_empty_content(self):
        """'chunked\nEND\n' is the complete encoding of a zero-length body.
        """
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        decoder.accept_bytes('END\n')
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(None, decoder.read_next_chunk())
        self.assertEqual('', decoder.unused_data)

    def test_one_chunk(self):
        """A body in a single chunk is decoded correctly."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunk_length = 'f\n'
        chunk_content = '123456789abcdef'
        finish = 'END\n'
        decoder.accept_bytes(chunk_length + chunk_content + finish)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(chunk_content, decoder.read_next_chunk())
        self.assertEqual('', decoder.unused_data)
        
    def test_incomplete_chunk(self):
        """When there are less bytes in the chunk than declared by the length,
        then we haven't finished reading yet.
        """
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunk_length = '8\n'
        three_bytes = '123'
        decoder.accept_bytes(chunk_length + three_bytes)
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(
            5 + 4, decoder.next_read_size(),
            "The next_read_size hint should be the number of missing bytes in "
            "this chunk plus 4 (the length of the end-of-body marker: "
            "'END\\n')")
        self.assertEqual(None, decoder.read_next_chunk())

    def test_incomplete_length(self):
        """A chunk length hasn't been read until a newline byte has been read.
        """
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        decoder.accept_bytes('9')
        self.assertEqual(
            1, decoder.next_read_size(),
            "The next_read_size hint should be 1, because we don't know the "
            "length yet.")
        decoder.accept_bytes('\n')
        self.assertEqual(
            9 + 4, decoder.next_read_size(),
            "The next_read_size hint should be the length of the chunk plus 4 "
            "(the length of the end-of-body marker: 'END\\n')")
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(None, decoder.read_next_chunk())

    def test_two_chunks(self):
        """Content from multiple chunks is concatenated."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunk_one = '3\naaa'
        chunk_two = '5\nbbbbb'
        finish = 'END\n'
        decoder.accept_bytes(chunk_one + chunk_two + finish)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual('aaa', decoder.read_next_chunk())
        self.assertEqual('bbbbb', decoder.read_next_chunk())
        self.assertEqual(None, decoder.read_next_chunk())
        self.assertEqual('', decoder.unused_data)

    def test_excess_bytes(self):
        """Bytes after the chunked body are reported as unused bytes."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunked_body = "5\naaaaaEND\n"
        excess_bytes = "excess bytes"
        decoder.accept_bytes(chunked_body + excess_bytes)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual('aaaaa', decoder.read_next_chunk())
        self.assertEqual(excess_bytes, decoder.unused_data)
        self.assertEqual(
            1, decoder.next_read_size(),
            "next_read_size hint should be 1 when finished_reading.")

    def test_multidigit_length(self):
        """Lengths in the chunk prefixes can have multiple digits."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        length = 0x123
        chunk_prefix = hex(length) + '\n'
        chunk_bytes = 'z' * length
        finish = 'END\n'
        decoder.accept_bytes(chunk_prefix + chunk_bytes + finish)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(chunk_bytes, decoder.read_next_chunk())

    def test_byte_at_a_time(self):
        """A complete body fed to the decoder one byte at a time should not
        confuse the decoder.  That is, it should give the same result as if the
        bytes had been received in one batch.

        This test is the same as test_one_chunk apart from the way accept_bytes
        is called.
        """
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunk_length = 'f\n'
        chunk_content = '123456789abcdef'
        finish = 'END\n'
        for byte in (chunk_length + chunk_content + finish):
            decoder.accept_bytes(byte)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(chunk_content, decoder.read_next_chunk())
        self.assertEqual('', decoder.unused_data)

    def test_read_pending_data_resets(self):
        """read_pending_data does not return the same bytes twice."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunk_one = '3\naaa'
        chunk_two = '3\nbbb'
        finish = 'END\n'
        decoder.accept_bytes(chunk_one)
        self.assertEqual('aaa', decoder.read_next_chunk())
        decoder.accept_bytes(chunk_two)
        self.assertEqual('bbb', decoder.read_next_chunk())
        self.assertEqual(None, decoder.read_next_chunk())

    def test_decode_error(self):
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunk_one = 'b\nfirst chunk'
        error_signal = 'ERR\n'
        error_chunks = '5\npart1' + '5\npart2'
        finish = 'END\n'
        decoder.accept_bytes(chunk_one + error_signal + error_chunks + finish)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual('first chunk', decoder.read_next_chunk())
        expected_failure = request.FailedSmartServerResponse(
            ('part1', 'part2'))
        self.assertEqual(expected_failure, decoder.read_next_chunk())

    def test_bad_header(self):
        """accept_bytes raises a SmartProtocolError if a chunked body does not
        start with the right header.
        """
        decoder = protocol.ChunkedBodyDecoder()
        self.assertRaises(
            errors.SmartProtocolError, decoder.accept_bytes, 'bad header\n')


class TestSuccessfulSmartServerResponse(tests.TestCase):

    def test_construct_no_body(self):
        response = request.SuccessfulSmartServerResponse(('foo', 'bar'))
        self.assertEqual(('foo', 'bar'), response.args)
        self.assertEqual(None, response.body)

    def test_construct_with_body(self):
        response = request.SuccessfulSmartServerResponse(
            ('foo', 'bar'), 'bytes')
        self.assertEqual(('foo', 'bar'), response.args)
        self.assertEqual('bytes', response.body)
        # repr(response) doesn't trigger exceptions.
        repr(response)

    def test_construct_with_body_stream(self):
        bytes_iterable = ['abc']
        response = request.SuccessfulSmartServerResponse(
            ('foo', 'bar'), body_stream=bytes_iterable)
        self.assertEqual(('foo', 'bar'), response.args)
        self.assertEqual(bytes_iterable, response.body_stream)

    def test_construct_rejects_body_and_body_stream(self):
        """'body' and 'body_stream' are mutually exclusive."""
        self.assertRaises(
            errors.BzrError,
            request.SuccessfulSmartServerResponse, (), 'body', ['stream'])

    def test_is_successful(self):
        """is_successful should return True for SuccessfulSmartServerResponse."""
        response = request.SuccessfulSmartServerResponse(('error',))
        self.assertEqual(True, response.is_successful())


class TestFailedSmartServerResponse(tests.TestCase):

    def test_construct(self):
        response = request.FailedSmartServerResponse(('foo', 'bar'))
        self.assertEqual(('foo', 'bar'), response.args)
        self.assertEqual(None, response.body)
        response = request.FailedSmartServerResponse(('foo', 'bar'), 'bytes')
        self.assertEqual(('foo', 'bar'), response.args)
        self.assertEqual('bytes', response.body)
        # repr(response) doesn't trigger exceptions.
        repr(response)

    def test_is_successful(self):
        """is_successful should return False for FailedSmartServerResponse."""
        response = request.FailedSmartServerResponse(('error',))
        self.assertEqual(False, response.is_successful())


class FakeHTTPMedium(object):
    def __init__(self):
        self.written_request = None
        self._current_request = None
    def send_http_smart_request(self, bytes):
        self.written_request = bytes
        return None


class HTTPTunnellingSmokeTest(tests.TestCase):

    def setUp(self):
        super(HTTPTunnellingSmokeTest, self).setUp()
        # We use the VFS layer as part of HTTP tunnelling tests.
        self._captureVar('BZR_NO_SMART_VFS', None)

    def test_smart_http_medium_request_accept_bytes(self):
        medium = FakeHTTPMedium()
        request = SmartClientHTTPMediumRequest(medium)
        request.accept_bytes('abc')
        request.accept_bytes('def')
        self.assertEqual(None, medium.written_request)
        request.finished_writing()
        self.assertEqual('abcdef', medium.written_request)


class RemoteHTTPTransportTestCase(tests.TestCase):

    def test_remote_path_after_clone_child(self):
        # If a user enters "bzr+http://host/foo", we want to sent all smart
        # requests for child URLs of that to the original URL.  i.e., we want to
        # POST to "bzr+http://host/foo/.bzr/smart" and never something like
        # "bzr+http://host/foo/.bzr/branch/.bzr/smart".  So, a cloned
        # RemoteHTTPTransport remembers the initial URL, and adjusts the relpaths
        # it sends in smart requests accordingly.
        base_transport = remote.RemoteHTTPTransport('bzr+http://host/path')
        new_transport = base_transport.clone('child_dir')
        self.assertEqual(base_transport._http_transport,
                         new_transport._http_transport)
        self.assertEqual('child_dir/foo', new_transport._remote_path('foo'))

    def test_remote_path_unnormal_base(self):
        # If the transport's base isn't normalised, the _remote_path should
        # still be calculated correctly.
        base_transport = remote.RemoteHTTPTransport('bzr+http://host/%7Ea/b')
        self.assertEqual('c', base_transport._remote_path('c'))

    def test_clone_unnormal_base(self):
        # If the transport's base isn't normalised, cloned transports should
        # still work correctly.
        base_transport = remote.RemoteHTTPTransport('bzr+http://host/%7Ea/b')
        new_transport = base_transport.clone('c')
        self.assertEqual('bzr+http://host/%7Ea/b/c/', new_transport.base)

        
# TODO: Client feature that does get_bundle and then installs that into a
# branch; this can be used in place of the regular pull/fetch operation when
# coming from a smart server.
#
# TODO: Eventually, want to do a 'branch' command by fetching the whole
# history as one big bundle.  How?  
#
# The branch command does 'br_from.sprout', which tries to preserve the same
# format.  We don't necessarily even want that.  
#
# It might be simpler to handle cmd_pull first, which does a simpler fetch()
# operation from one branch into another.  It already has some code for
# pulling from a bundle, which it does by trying to see if the destination is
# a bundle file.  So it seems the logic for pull ought to be:
# 
#  - if it's a smart server, get a bundle from there and install that
#  - if it's a bundle, install that
#  - if it's a branch, pull from there
#
# Getting a bundle from a smart server is a bit different from reading a
# bundle from a URL:
#
#  - we can reasonably remember the URL we last read from 
#  - you can specify a revision number to pull, and we need to pass it across
#    to the server as a limit on what will be requested
#
# TODO: Given a URL, determine whether it is a smart server or not (or perhaps
# otherwise whether it's a bundle?)  Should this be a property or method of
# the transport?  For the ssh protocol, we always know it's a smart server.
# For http, we potentially need to probe.  But if we're explicitly given
# bzr+http:// then we can skip that for now. 
