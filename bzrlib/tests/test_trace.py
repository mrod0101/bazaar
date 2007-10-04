# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

# "weren't nothing promised to you.  do i look like i got a promise face?"

"""Tests for trace library"""

from cStringIO import StringIO
import errno
import os
import sys

from bzrlib import (
    errors,
    )
from bzrlib.tests import TestCaseInTempDir, TestCase
from bzrlib.trace import (
    mutter, mutter_callsite, report_exception,
    set_verbosity_level, get_verbosity_level, is_quiet, is_verbose, be_quiet,
    _rollover_trace_maybe,
    )


def _format_exception():
    """Format an exception as it would normally be displayed to the user"""
    buf = StringIO()
    report_exception(sys.exc_info(), buf)
    return buf.getvalue()


class TestTrace(TestCase):

    def test_format_sys_exception(self):
        try:
            raise NotImplementedError, "time travel"
        except NotImplementedError:
            pass
        err = _format_exception()
        self.assertEqualDiff(err.splitlines()[0],
                'bzr: ERROR: exceptions.NotImplementedError: time travel')
        self.assertContainsRe(err,
                r'File.*test_trace.py')

    def test_format_interrupt_exception(self):
        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            # XXX: Some risk that a *real* keyboard interrupt won't be seen
            pass
        msg = _format_exception()
        self.assertTrue(len(msg) > 0)
        self.assertEqualDiff(msg, 'bzr: interrupted\n')

    def test_format_os_error(self):
        try:
            file('nosuchfile22222')
        except (OSError, IOError):
            pass
        msg = _format_exception()
        self.assertContainsRe(msg, r'^bzr: ERROR: \[Errno .*\] No such file.*nosuchfile')

    def test_format_unicode_error(self):
        try:
            raise errors.BzrCommandError(u'argument foo\xb5 does not exist')
        except errors.BzrCommandError:
            pass
        msg = _format_exception()

    def test_format_exception(self):
        """Short formatting of bzr exceptions"""
        try:
            raise errors.NotBranchError('wibble')
        except errors.NotBranchError:
            pass
        msg = _format_exception()
        self.assertTrue(len(msg) > 0)
        self.assertEqualDiff(msg, 'bzr: ERROR: Not a branch: \"wibble\".\n')

    def test_trace_unicode(self):
        """Write Unicode to trace log"""
        self.log(u'the unicode character for benzene is \N{BENZENE RING}')
        self.assertContainsRe(self._get_log(keep_log_file=True),
                              "the unicode character for benzene is")
    
    def test_trace_argument_unicode(self):
        """Write a Unicode argument to the trace log"""
        mutter(u'the unicode character for benzene is %s', u'\N{BENZENE RING}')
        self.assertContainsRe(self._get_log(keep_log_file=True),
                              'the unicode character')

    def test_trace_argument_utf8(self):
        """Write a Unicode argument to the trace log"""
        mutter(u'the unicode character for benzene is %s',
               u'\N{BENZENE RING}'.encode('utf-8'))
        self.assertContainsRe(self._get_log(keep_log_file=True),
                              'the unicode character')

    def test_report_broken_pipe(self):
        try:
            raise IOError(errno.EPIPE, 'broken pipe foofofo')
        except IOError, e:
            msg = _format_exception()
            self.assertEquals(msg, "bzr: broken pipe\n")
        else:
            self.fail("expected error not raised")

    def test_mutter_callsite_1(self):
        """mutter_callsite can capture 1 level of stack frame."""
        mutter_callsite(1, "foo %s", "a string")
        log = self._get_log(keep_log_file=True)
        # begin with the message
        self.assertStartsWith(log, 'foo a string\nCalled from:\n')
        # should show two frame: this frame and the one above
        self.assertContainsRe(log,
            'test_trace\.py", line \d+, in test_mutter_callsite_1\n')
        # this frame should be the final one
        self.assertEndsWith(log, ' "a string")\n')

    def test_mutter_callsite_2(self):
        """mutter_callsite can capture 2 levels of stack frame."""
        mutter_callsite(2, "foo %s", "a string")
        log = self._get_log(keep_log_file=True)
        # begin with the message
        self.assertStartsWith(log, 'foo a string\nCalled from:\n')
        # should show two frame: this frame and the one above
        self.assertContainsRe(log,
            'test_trace.py", line \d+, in test_mutter_callsite_2\n')
        # this frame should be the final one
        self.assertEndsWith(log, ' "a string")\n')

    def test_mutter_never_fails(self):
        # Even if the decode/encode stage fails, mutter should not
        # raise an exception
        mutter(u'Writing a greek mu (\xb5) works in a unicode string')
        mutter('But fails in an ascii string \xb5')
        mutter('and in an ascii argument: %s', '\xb5')
        log = self._get_log(keep_log_file=True)
        self.assertContainsRe(log, 'Writing a greek mu')
        self.assertContainsRe(log, "But fails in an ascii string")
        self.assertContainsRe(log, u"ascii argument: \xb5")


class TestVerbosityLevel(TestCase):

    def test_verbosity_level(self):
        set_verbosity_level(1)
        self.assertEqual(1, get_verbosity_level())
        self.assertTrue(is_verbose())
        self.assertFalse(is_quiet())
        set_verbosity_level(-1)
        self.assertEqual(-1, get_verbosity_level())
        self.assertFalse(is_verbose())
        self.assertTrue(is_quiet())
        set_verbosity_level(0)
        self.assertEqual(0, get_verbosity_level())
        self.assertFalse(is_verbose())
        self.assertFalse(is_quiet())

    def test_be_quiet(self):
        # Confirm the old API still works
        be_quiet(True)
        self.assertEqual(-1, get_verbosity_level())
        be_quiet(False)
        self.assertEqual(0, get_verbosity_level())


class TestBzrLog(TestCaseInTempDir):

    def test_log_rollover(self):
        temp_log_name = 'test-log'
        trace_file = open(temp_log_name, 'at')
        trace_file.write('test_log_rollover padding\n' * 1000000)
        trace_file.close()
        _rollover_trace_maybe(temp_log_name)
        # should have been rolled over
        self.assertFalse(os.access(temp_log_name, os.R_OK))
