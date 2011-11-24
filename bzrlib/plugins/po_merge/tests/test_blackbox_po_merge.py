# -*- coding: utf8
# Copyright (C) 2011 by Canonical Ltd
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

import os

from bzrlib import (
    merge,
    tests,
    )
from bzrlib.tests import (
    features,
    script,
    )

from bzrlib.plugins import po_merge

class BlackboxTestPoMerger(script.TestCaseWithTransportAndScript):

    _test_needs_features = [features.msgmerge_feature]

    def setUp(self):
        super(BlackboxTestPoMerger, self).setUp()
        self.builder = make_adduser_branch(self, 'adduser')
        # We need to install our hook as the test framework cleared it as part
        # of the initialization
        merge.Merger.hooks.install_named_hook(
            "merge_file_content", po_merge.po_merge_hook, ".po file merge")

    def test_merge_with_hook_gives_unexpected_results(self):
        # Since the conflicts in .pot are not seen *during* the merge, the .po
        # merge triggers the hook and create no conflicts. But the .pot used is
        # the one present in the tree *before* the merge.
        self.run_script("""\
$ bzr branch adduser -rrevid:this work
2>Branched 2 revisions.
$ cd work
$ bzr config po_merge.pot_file=adduser.pot
$ bzr config po_merge.po_files=fr.po
$ bzr merge ../adduser -rrevid:other
2> M  adduser.pot
2> M  fr.po
2>Text conflict in adduser.pot
2>1 conflicts encountered.
""")

    def test_called_on_remerge(self):
        # Merge with no config for the hook to create the conflicts
        self.run_script("""\
$ bzr branch adduser -rrevid:this work
2>Branched 2 revisions.
$ cd work
$ bzr merge ../adduser -rrevid:other
2> M  adduser.pot
2> M  fr.po
2>Text conflict in adduser.pot
2>Text conflict in fr.po
2>2 conflicts encountered.
""")
        # Fix the conflicts in the .pot file
        with open('adduser.pot', 'w') as f:
            f.write(_adduser_branch['resolved_pot'])
        # Tell bzr the conflict is resolved
        self.run_script("""\
$ bzr resolve adduser.pot
2>1 conflict resolved, 1 remaining
""")
        # set config options to activate the hook
        self.run_script("""\
$ bzr config po_merge.pot_file=adduser.pot
$ bzr config po_merge.po_files=fr.po
""")
        # Use remerge to trigger the hook, 
        self.run_script("""\
$ bzr remerge *.po
2>All changes applied successfully.
""")
        # There should be no conflicts anymore
        self.run_script("""\
$ bzr conflicts
""")


def make_adduser_branch(test, relpath):
    """Helper for po_merge blackbox tests.

    This creates a branch containing the needed base revisions so tests can
    attempt merges and conflict resolutions.
    """
    builder = test.make_branch_builder(relpath)
    builder.start_series()
    builder.build_snapshot('base', None,
                           [('add', ('', 'root-id', 'directory', '')),
                            # Create empty files
                            ('add', ('adduser.pot', 'pot-id', 'file',
                                     _adduser_branch['base_pot'])),
                            ('add', ('fr.po', 'po-id', 'file',
                                     _adduser_branch['base_po'])),
            ])
    # The 'other' branch
    builder.build_snapshot('other', ['base'],
                           [('modify', ('pot-id',
                                        _adduser_branch['other_pot'])),
                            ('modify', ('po-id',
                                        _adduser_branch['other_po'])),
                            ])
    # The 'this' branch
    builder.build_snapshot('this', ['base'],
                           [('modify', ('pot-id', _adduser_branch['this_pot'])),
                            ('modify', ('po-id', _adduser_branch['this_po'])),
                            ])
    # builder.get_branch() tip is now 'this'
    builder.finish_series()
    return builder


class TestAdduserBranch(script.TestCaseWithTransportAndScript):
    """Sanity checks on the adduser branch content."""

    def setUp(self):
        super(TestAdduserBranch, self).setUp()
        self.builder = make_adduser_branch(self, 'adduser')

    def assertAdduserBranchContent(self, revid):
        env = dict(revid=revid, branch_name=revid)
        self.run_script("""\
$ bzr branch adduser -rrevid:%(revid)s %(branch_name)s
""" % env, null_output_matches_anything=True)
        self.assertFileEqual(_adduser_branch['%(revid)s_pot' % env],
                             '%(branch_name)s/adduser.pot' % env)
        self.assertFileEqual(_adduser_branch['%(revid)s_po' % env],
                             '%(branch_name)s/fr.po' % env )

    def test_base(self):
        self.assertAdduserBranchContent('base')

    def test_this(self):
        self.assertAdduserBranchContent('this')

    def test_other(self):
        self.assertAdduserBranchContent('other')


# Real content from the adduser package so we don't have to guess about format
# details. This is declared at the end of the file to avoid cluttering the
# beginning of the file.

_adduser_branch = dict(
    base_pot = r"""# SOME DESCRIPTIVE TITLE.
# Copyright (C) YEAR THE PACKAGE'S COPYRIGHT HOLDER
# This file is distributed under the same license as the PACKAGE package.
# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.
#
#, fuzzy
msgid ""
msgstr ""
"Project-Id-Version: PACKAGE VERSION\n"
"Report-Msgid-Bugs-To: adduser-devel@lists.alioth.debian.org\n"
"POT-Creation-Date: 2007-01-17 21:50+0100\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: LANGUAGE <LL@li.org>\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=CHARSET\n"
"Content-Transfer-Encoding: 8bit\n"

#. everyone can issue "--help" and "--version", but only root can go on
#: ../adduser:135
msgid "Only root may add a user or group to the system.\n"
msgstr ""

#: ../adduser:188
msgid "Warning: The home dir you specified already exists.\n"
msgstr ""

""",
    this_pot = r"""# SOME DESCRIPTIVE TITLE.
# Copyright (C) YEAR THE PACKAGE'S COPYRIGHT HOLDER
# This file is distributed under the same license as the PACKAGE package.
# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.
#
#, fuzzy
msgid ""
msgstr ""
"Project-Id-Version: PACKAGE VERSION\n"
"Report-Msgid-Bugs-To: adduser-devel@lists.alioth.debian.org\n"
"POT-Creation-Date: 2011-01-06 21:06+0000\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: LANGUAGE <LL@li.org>\n"
"Language: \n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=CHARSET\n"
"Content-Transfer-Encoding: 8bit\n"

#. everyone can issue "--help" and "--version", but only root can go on
#: ../adduser:152
msgid "Only root may add a user or group to the system.\n"
msgstr ""

#: ../adduser:208
#, perl-format
msgid "Warning: The home dir %s you specified already exists.\n"
msgstr ""

#: ../adduser:210
#, perl-format
msgid "Warning: The home dir %s you specified can't be accessed: %s\n"
msgstr ""

""",
    other_pot = r"""# SOME DESCRIPTIVE TITLE.
# Copyright (C) YEAR THE PACKAGE'S COPYRIGHT HOLDER
# This file is distributed under the same license as the PACKAGE package.
# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.
#
#, fuzzy
msgid ""
msgstr ""
"Project-Id-Version: PACKAGE VERSION\n"
"Report-Msgid-Bugs-To: adduser-devel@lists.alioth.debian.org\n"
"POT-Creation-Date: 2010-11-21 17:13-0400\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: LANGUAGE <LL@li.org>\n"
"Language: \n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=CHARSET\n"
"Content-Transfer-Encoding: 8bit\n"

#. everyone can issue "--help" and "--version", but only root can go on
#: ../adduser:150
msgid "Only root may add a user or group to the system.\n"
msgstr ""

#: ../adduser:206
#, perl-format
msgid "Warning: The home dir %s you specified already exists.\n"
msgstr ""

#: ../adduser:208
#, perl-format
msgid "Warning: The home dir %s you specified can't be accessed: %s\n"
msgstr ""

""",
    resolved_pot = r"""# SOME DESCRIPTIVE TITLE.
# Copyright (C) YEAR THE PACKAGE'S COPYRIGHT HOLDER
# This file is distributed under the same license as the PACKAGE package.
# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.
#
#, fuzzy
msgid ""
msgstr ""
"Project-Id-Version: PACKAGE VERSION\n"
"Report-Msgid-Bugs-To: adduser-devel@lists.alioth.debian.org\n"
"POT-Creation-Date: 2011-10-19 12:50-0700\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: LANGUAGE <LL@li.org>\n"
"Language: \n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=CHARSET\n"
"Content-Transfer-Encoding: 8bit\n"

#. everyone can issue "--help" and "--version", but only root can go on
#: ../adduser:152
msgid "Only root may add a user or group to the system.\n"
msgstr ""

#: ../adduser:208
#, perl-format
msgid "Warning: The home dir %s you specified already exists.\n"
msgstr ""

#: ../adduser:210
#, perl-format
msgid "Warning: The home dir %s you specified can't be accessed: %s\n"
msgstr ""

""",
    base_po = r"""# adduser's manpages translation to French
# Copyright (C) 2004 Software in the Public Interest
# This file is distributed under the same license as the adduser package
#
# Translators:
# Jean-Baka Domelevo Entfellner <domelevo@gmail.com>, 2009.
#
msgid ""
msgstr ""
"Project-Id-Version: adduser 3.111\n"
"Report-Msgid-Bugs-To: adduser-devel@lists.alioth.debian.org\n"
"POT-Creation-Date: 2007-01-17 21:50+0100\n"
"PO-Revision-Date: 2010-01-21 10:36+0100\n"
"Last-Translator: Jean-Baka Domelevo Entfellner <domelevo@gmail.com>\n"
"Language-Team: Debian French Team <debian-l10n-french@lists.debian.org>\n"
"Language: \n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
"X-Poedit-Language: French\n"
"X-Poedit-Country: FRANCE\n"

# type: Plain text
#. everyone can issue "--help" and "--version", but only root can go on
#: ../adduser:135
msgid "Only root may add a user or group to the system.\n"
msgstr ""
"Seul le superutilisateur est autorisé à ajouter un utilisateur ou un groupe "
"au système.\n"

#: ../adduser:188
msgid "Warning: The home dir you specified already exists.\n"
msgstr ""
"Attention ! Le répertoire personnel que vous avez indiqué existe déjà.\n"

""",
    this_po = r"""# adduser's manpages translation to French
# Copyright (C) 2004 Software in the Public Interest
# This file is distributed under the same license as the adduser package
#
# Translators:
# Jean-Baka Domelevo Entfellner <domelevo@gmail.com>, 2009.
#
msgid ""
msgstr ""
"Project-Id-Version: adduser 3.111\n"
"Report-Msgid-Bugs-To: adduser-devel@lists.alioth.debian.org\n"
"POT-Creation-Date: 2010-10-12 15:48+0200\n"
"PO-Revision-Date: 2010-01-21 10:36+0100\n"
"Last-Translator: Jean-Baka Domelevo Entfellner <domelevo@gmail.com>\n"
"Language-Team: Debian French Team <debian-l10n-french@lists.debian.org>\n"
"Language: \n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
"X-Poedit-Language: French\n"
"X-Poedit-Country: FRANCE\n"

# type: Plain text
#. everyone can issue "--help" and "--version", but only root can go on
#: ../adduser:152
msgid "Only root may add a user or group to the system.\n"
msgstr ""
"Seul le superutilisateur est autorisé à ajouter un utilisateur ou un groupe "
"au système.\n"

#: ../adduser:208
#, fuzzy, perl-format
msgid "Warning: The home dir %s you specified already exists.\n"
msgstr ""
"Attention ! Le répertoire personnel que vous avez indiqué existe déjà.\n"

#: ../adduser:210
#, fuzzy, perl-format
msgid "Warning: The home dir %s you specified can't be accessed: %s\n"
msgstr ""
"Attention ! Le répertoire personnel que vous avez indiqué existe déjà.\n"

""",
    other_po = r"""# adduser's manpages translation to French
# Copyright (C) 2004 Software in the Public Interest
# This file is distributed under the same license as the adduser package
#
# Translators:
# Jean-Baka Domelevo Entfellner <domelevo@gmail.com>, 2009, 2010.
#
msgid ""
msgstr ""
"Project-Id-Version: adduser 3.112+nmu2\n"
"Report-Msgid-Bugs-To: adduser-devel@lists.alioth.debian.org\n"
"POT-Creation-Date: 2010-11-21 17:13-0400\n"
"PO-Revision-Date: 2010-11-10 11:08+0100\n"
"Last-Translator: Jean-Baka Domelevo-Entfellner <domelevo@gmail.com>\n"
"Language-Team: Debian French Team <debian-l10n-french@lists.debian.org>\n"
"Language: \n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
"X-Poedit-Country: FRANCE\n"

# type: Plain text
#. everyone can issue "--help" and "--version", but only root can go on
#: ../adduser:150
msgid "Only root may add a user or group to the system.\n"
msgstr ""
"Seul le superutilisateur est autorisé à ajouter un utilisateur ou un groupe "
"au système.\n"

#: ../adduser:206
#, perl-format
msgid "Warning: The home dir %s you specified already exists.\n"
msgstr ""
"Attention ! Le répertoire personnel que vous avez indiqué (%s) existe déjà.\n"

#: ../adduser:208
#, perl-format
msgid "Warning: The home dir %s you specified can't be accessed: %s\n"
msgstr ""
"Attention ! Impossible d'accéder au répertoire personnel que vous avez "
"indiqué (%s) : %s.\n"

""",
    resolved_po = r"""# adduser's manpages translation to French
# Copyright (C) 2004 Software in the Public Interest
# This file is distributed under the same license as the adduser package
#
# Translators:
# Jean-Baka Domelevo Entfellner <domelevo@gmail.com>, 2009, 2010.
#
msgid ""
msgstr ""
"Project-Id-Version: adduser 3.112+nmu2\n"
"Report-Msgid-Bugs-To: adduser-devel@lists.alioth.debian.org\n"
"POT-Creation-Date: 2011-10-19 12:50-0700\n"
"PO-Revision-Date: 2010-11-10 11:08+0100\n"
"Last-Translator: Jean-Baka Domelevo-Entfellner <domelevo@gmail.com>\n"
"Language-Team: Debian French Team <debian-l10n-french@lists.debian.org>\n"
"Language: \n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
"X-Poedit-Country: FRANCE\n"

# type: Plain text
#. everyone can issue "--help" and "--version", but only root can go on
#: ../adduser:152
msgid "Only root may add a user or group to the system.\n"
msgstr ""
"Seul le superutilisateur est autorisé à ajouter un utilisateur ou un groupe "
"au système.\n"

#: ../adduser:208
#, perl-format
msgid "Warning: The home dir %s you specified already exists.\n"
msgstr ""
"Attention ! Le répertoire personnel que vous avez indiqué (%s) existe déjà.\n"

#: ../adduser:210
#, perl-format
msgid "Warning: The home dir %s you specified can't be accessed: %s\n"
msgstr ""
"Attention ! Impossible d'accéder au répertoire personnel que vous avez "
"indiqué (%s) : %s.\n"

""",
)
