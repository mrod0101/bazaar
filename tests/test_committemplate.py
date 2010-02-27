# Copyright (C) 2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for the commit template creation."""

from bzrlib.plugins import commitfromnews
from bzrlib import msgeditor
from bzrlib.tests import TestCaseWithTransport

class TestCommitTemplate(TestCaseWithTransport):

    def capture_template(self, commit, message):
        self.messages.append(message)
        if message is None:
            message = 'let this commit succeed I command thee.'
        return message

    def setup_capture(self):
        commitfromnews.register()
        msgeditor.hooks.install_named_hook('commit_message_template',
            self.capture_template, 'commitfromnews test template')
        self.messages = []

    def test_initial(self):
        self.setup_capture()
        builder = self.make_branch_builder('test')
        builder.start_series()
        builder.build_snapshot('BASE-id', None,
            [('add', ('', None, 'directory', None)),
             ('add', ('foo', 'foo-id', 'file', 'a\nb\nc\nd\ne\n')),
             ],
            message_callback=msgeditor.generate_commit_message_template)
        builder.finish_series()
        self.assertEqual([None], self.messages)

    def test_added_NEWS(self):
        self.setup_capture()
        builder = self.make_branch_builder('test')
        builder.start_series()
        content = """----------------------------
commitfromnews release notes
----------------------------

NEXT (In development)
---------------------

IMPROVEMENTS
~~~~~~~~~~~~

* Created plugin, basic functionality of looking for NEWS and including the
  NEWS diff.
"""
        builder.build_snapshot('BASE-id', None,
            [('add', ('', None, 'directory', None)),
             ('add', ('NEWS', 'foo-id', 'file', content)),
             ],
            message_callback=msgeditor.generate_commit_message_template)
        builder.finish_series()
        self.assertEqual([content], self.messages)

    def test_changed_NEWS(self):
        self.setup_capture()
        builder = self.make_branch_builder('test')
        builder.start_series()
        orig_content = """----------------------------
commitfromnews release notes
----------------------------

NEXT (In development)
---------------------

IMPROVEMENTS
~~~~~~~~~~~~

* Created plugin, basic functionality of looking for NEWS and including the
  NEWS diff.
"""
        mod_content = """----------------------------
commitfromnews release notes
----------------------------

NEXT (In development)
---------------------

IMPROVEMENTS
~~~~~~~~~~~~

* Added a new change to the system.

* Created plugin, basic functionality of looking for NEWS and including the
  NEWS diff.
"""
        change_content = """* Added a new change to the system.

"""
        builder.build_snapshot('BASE-id', None,
            [('add', ('', None, 'directory', None)),
             ('add', ('NEWS', 'foo-id', 'file', orig_content)),
             ])
        builder.build_snapshot(None, None,
            [('modify', ('foo-id', mod_content)),
             ],
            message_callback=msgeditor.generate_commit_message_template)
        builder.finish_series()
        self.assertEqual([change_content], self.messages)

    def _todo_test_passes_messages_through(self):
        pass
