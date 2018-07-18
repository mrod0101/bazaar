# Copyright (C) 2005-2012, 2016, 2017 Canonical Ltd
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

# A relatively simple Makefile to assist in building parts of brz. Mostly for
# building documentation, etc.


### Core Stuff ###

SHELL=bash
PYTHON?=python
PYTHON3?=python3
PYTHON24=python24
PYTHON25=python25
PYTHON26=python26
BRZ_TARGET=release
PLUGIN_TARGET=plugin-release
PYTHON_BUILDFLAGS=
BRZ_PLUGIN_PATH=-site:-user

# Shorter replacement for $(sort $(wildcard <arg>)) as $(call sw,<arg>)
sw = $(sort $(wildcard $(1)))


.PHONY: all clean realclean extensions pyflakes api-docs check-nodocs check

all: extensions

extensions:
	@echo "building extension modules."
	$(PYTHON) setup.py build_ext -i $(PYTHON_BUILDFLAGS)

check: docs check-nodocs

check-nodocs: check-nodocs2 check-nodocs3

check-nodocs3:
	# Generate a stream for PQM to watch.
	-$(RM) -f selftest.log
	echo `date` ": selftest starts" 1>&2
	set -o pipefail; BRZ_PLUGIN_PATH=$(BRZ_PLUGIN_PATH) $(PYTHON3) -Werror -Wignore::ImportWarning -Wignore::PendingDeprecationWarning -Wignore::DeprecationWarning -O \
	  ./brz selftest -Oselftest.timeout=120 --load-list=python3.passing \
	  --subunit2 $(tests) | tee selftest.log | subunit-2to1
	echo `date` ": selftest ends" 1>&2
	# An empty log file should catch errors in the $(PYTHON3)
	# command above (the '|' swallow any errors since 'make'
	# sees the 'tee' exit code for the whole line
	if [ ! -s selftest.log ] ; then exit 1 ; fi
	# Check that there were no errors reported.
	subunit-stats < selftest.log

update-python3-passing:
	# Generate a stream for PQM to watch.
	-$(RM) -f selftest.log
	-BRZ_PLUGIN_PATH=$(BRZ_PLUGIN_PATH) $(PYTHON3) -Werror -Wignore::ImportWarning -Wignore::DeprecationWarning -O \
	  ./brz selftest -Oselftest.timeout=120 \
	  --subunit2 $(tests) > selftest.log
	grep -v "^#" python3.passing > python3.passing.new
	cat selftest.log | \
	  subunit-filter --no-failure --no-error --success | \
	  subunit-ls --no-passthrough >> python3.passing.new
	cp python3.passing python3.passing.old
	grep "^#" python3.passing.old > python3.passing
	grep -Fvxf python3.flapping python3.passing.new > python3.passing.new.solid
	sort -u python3.passing.new.solid >> python3.passing

check-nodocs2: extensions
	# Generate a stream for PQM to watch.
	-$(RM) -f selftest.log
	echo `date` ": selftest starts" 1>&2
	set -o pipefail; BRZ_PLUGIN_PATH=$(BRZ_PLUGIN_PATH) $(PYTHON) -Werror -Wignore::ImportWarning -Wignore::DeprecationWarning -O \
	  ./brz selftest -Oselftest.timeout=120 \
	  --subunit2 $(tests) | tee selftest.log | subunit-2to1
	echo `date` ": selftest ends" 1>&2
	# An empty log file should catch errors in the $(PYTHON)
	# command above (the '|' swallow any errors since 'make'
	# sees the 'tee' exit code for the whole line
	if [ ! -s selftest.log ] ; then exit 1 ; fi
	# Check that there were no errors reported.
	subunit-stats < selftest.log

check-ci: docs extensions
	# FIXME: Remove -Wignore::FutureWarning once
	# https://github.com/paramiko/paramiko/issues/713 is not a concern
	# anymore -- vila 2017-05-24
	set -o pipefail; \
	BRZ_PLUGIN_PATH=$(BRZ_PLUGIN_PATH) $(PYTHON) -Werror -Wignore::FutureWarning -Wignore::DeprecationWarning -Wignore::ImportWarning -Wignore::ResourceWarning -O \
	  ./brz selftest -v --parallel=fork -Oselftest.timeout=120 --subunit2 \
	  | subunit-filter -s --passthrough --rename "^" "python2."; \
	  BRZ_PLUGIN_PATH=$(BRZ_PLUGIN_PATH) $(PYTHON3) -Werror -Wignore::FutureWarning -Wignore::DeprecationWarning -Wignore::PendingDeprecationWarning -Wignore::ImportWarning -O \
	  ./brz selftest -v --parallel=fork -Oselftest.timeout=120 --load-list=python3.passing --subunit2 \
	  | subunit-filter -s --passthrough --rename "^" "python3."

# Run Python style checker (apt-get install pyflakes)
#
# Note that at present this gives many false warnings, because it doesn't
# know about identifiers loaded through lazy_import.
pyflakes:
	pyflakes breezy

pyflakes-nounused:
	# There are many of these warnings at the moment and they're not a
	# high priority to fix
	pyflakes breezy | grep -v ' imported but unused'

clean:
	$(PYTHON) setup.py clean
	-find . -name "*.pyc" -o -name "*.pyo" -o -name "*.so" | xargs rm -f

realclean: clean
	# Remove files which are autogenerated but included by the tarball.
	rm -f breezy/*_pyx.c breezy/bzr/*_pyx.c
	rm -f breezy/_simple_set_pyx.h breezy/_simple_set_pyx_api.h

# Build API documentation
docfiles = brz breezy
api-docs:
	mkdir -p api/html
	pydoctor --make-html --docformat='restructuredtext' --html-output=api/html $(docfiles)

# build tags for emacs and vim
TAGS:
	ctags -R -e breezy

tags:
	ctags -R breezy

# these are treated as phony so they'll always be rebuilt - it's pretty quick
.PHONY: TAGS tags


### Documentation ###

# Default to plain documentation for maximum backwards compatibility.
# (Post 2.0, the defaults will most likely be Sphinx-style instead.)

docs: docs-plain

clean-docs: clean-plain

html-docs: html-plain


### Man-page Documentation ###

MAN_DEPENDENCIES = breezy/builtins.py \
	$(call sw,breezy/*.py) \
	$(call sw,breezy/*/*.py) \
	tools/generate_docs.py \
	$(call sw,$(addsuffix /*.txt, breezy/help_topics/en)) 

MAN_PAGES = man1/brz.1
man1/brz.1: $(MAN_DEPENDENCIES)
	mkdir -p $(dir $@)
	$(PYTHON) tools/generate_docs.py -o $@ man


### Sphinx-style Documentation ###

# Build the documentation. To keep the dependencies down to a minimum
# for distro packagers, we only build the html documentation by default.
# Sphinx 0.6 or later is preferred for the best rendering, though
# Sphinx 0.4 or later should work. See http://sphinx.pocoo.org/index.html
# for installation instructions.
docs-sphinx: html-sphinx

# Clean out generated documentation
clean-sphinx:
	cd doc/en && make clean
	cd doc/developers && make clean

SPHINX_DEPENDENCIES = \
        doc/en/release-notes/index.txt \
        doc/en/user-reference/index.txt \
	doc/developers/Makefile \
	doc/developers/make.bat

NEWS_FILES = $(call sw,doc/en/release-notes/brz-*.txt)

doc/en/user-reference/index.txt: $(MAN_DEPENDENCIES)
	LANGUAGE=C $(PYTHON) tools/generate_docs.py -o $@ rstx

doc/en/release-notes/index.txt: $(NEWS_FILES) tools/generate_release_notes.py
	$(PYTHON) tools/generate_release_notes.py $@ $(NEWS_FILES)

doc/%/Makefile: doc/en/Makefile
	$(PYTHON) -c "import shutil; shutil.copyfile('$<', '$@')"

doc/%/make.bat: doc/en/make.bat
	$(PYTHON) -c "import shutil; shutil.copyfile('$<', '$@')"

# Build the html docs using Sphinx.
html-sphinx: $(SPHINX_DEPENDENCIES)
	cd doc/en && make html
	cd doc/developers && make html

# Build the PDF docs using Sphinx. This requires numerous LaTeX
# packages. See http://sphinx.pocoo.org/builders.html for details.
# Note: We don't currently build PDFs for the Russian docs because
# they require additional packages to be installed (to handle
# Russian hyphenation rules, etc.)
pdf-sphinx: $(SPHINX_DEPENDENCIES)
	cd doc/en && make latex
	cd doc/developers && make latex
	cd doc/en/_build/latex && make all-pdf
	cd doc/developers/_build/latex && make all-pdf

# Build the CHM (Windows Help) docs using Sphinx.
# Note: HtmlHelp Workshop needs to be used on the generated hhp files
# to generate the final chm files.
chm-sphinx: $(SPHINX_DEPENDENCIES)
	cd doc/en && make htmlhelp
	cd doc/developers && make htmlhelp


# Build the texinfo files using Sphinx.
texinfo-sphinx: $(SPHINX_DEPENDENCIES)
	cd doc/en && make texinfo
	cd doc/developers && make texinfo

### Documentation Website ###

# Where to build the website
DOC_WEBSITE_BUILD = build_doc_website

# Build and package docs into a website, complete with downloads.
doc-website: html-sphinx pdf-sphinx
	$(PYTHON) tools/package_docs.py doc/en $(DOC_WEBSITE_BUILD)
	$(PYTHON) tools/package_docs.py doc/developers $(DOC_WEBSITE_BUILD)


### Plain Documentation ###

# While Sphinx is the preferred tool for building documentation, we still
# support our "plain" html documentation so that Sphinx is not a hard
# dependency for packagers on older platforms.

rst2html = $(PYTHON) tools/rst2html.py --link-stylesheet --footnote-references=superscript --halt=warning

# translate txt docs to html
derived_txt_files = \
	doc/en/release-notes/NEWS.txt
txt_all = \
	doc/en/tutorials/tutorial.txt \
	doc/en/tutorials/using_breezy_with_launchpad.txt \
	doc/en/tutorials/centralized_workflow.txt \
	$(call sw,doc/*/mini-tutorial/index.txt) \
	$(call sw,doc/*/user-guide/index-plain.txt) \
	doc/en/admin-guide/index-plain.txt \
	$(call sw,doc/es/guia-usario/*.txt) \
	$(derived_txt_files) \
	doc/en/upgrade-guide/index.txt \
	doc/index.txt \
	$(call sw,doc/index.*.txt)
txt_nohtml = \
	doc/en/user-guide/index.txt \
	doc/en/admin-guide/index.txt
txt_files = $(filter-out $(txt_nohtml), $(txt_all))
htm_files = $(patsubst %.txt, %.html, $(txt_files)) 

non_txt_files = \
       doc/default.css \
       $(call sw,doc/*/brz-en-quick-reference.svg) \
       $(call sw,doc/*/brz-en-quick-reference.png) \
       $(call sw,doc/*/brz-en-quick-reference.pdf) \
       $(call sw,doc/*/bzr-es-quick-reference.svg) \
       $(call sw,doc/*/bzr-es-quick-reference.png) \
       $(call sw,doc/*/bzr-es-quick-reference.pdf) \
       $(call sw,doc/*/bzr-ru-quick-reference.svg) \
       $(call sw,doc/*/bzr-ru-quick-reference.png) \
       $(call sw,doc/*/bzr-ru-quick-reference.pdf) \
       $(call sw,doc/*/user-guide/images/*.png)

# doc/developers/*.txt files that should *not* be individually
# converted to HTML
dev_txt_nohtml = \
	doc/developers/add.txt \
	doc/developers/annotate.txt \
	doc/developers/bundle-creation.txt \
	doc/developers/commit.txt \
	doc/developers/diff.txt \
	doc/developers/directory-fingerprints.txt \
	doc/developers/gc.txt \
	doc/developers/implementation-notes.txt \
	doc/developers/incremental-push-pull.txt \
	doc/developers/index.txt \
	doc/developers/initial-push-pull.txt \
	doc/developers/merge-scaling.txt \
	doc/developers/miscellaneous-notes.txt \
	doc/developers/missing.txt \
	doc/developers/performance-roadmap-rationale.txt \
	doc/developers/performance-use-case-analysis.txt \
	doc/developers/planned-change-integration.txt \
	doc/developers/planned-performance-changes.txt \
	doc/developers/plans.txt \
	doc/developers/process.txt \
	doc/developers/revert.txt \
	doc/developers/specifications.txt \
	doc/developers/status.txt \
	doc/developers/uncommit.txt

dev_txt_all = $(call sw,$(addsuffix /*.txt, doc/developers))
dev_txt_files = $(filter-out $(dev_txt_nohtml), $(dev_txt_all))
dev_htm_files = $(patsubst %.txt, %.html, $(dev_txt_files)) 

doc/en/user-guide/index-plain.html: $(call sw,$(addsuffix /*.txt, doc/en/user-guide))
	$(rst2html) --stylesheet=../../default.css $(dir $@)index-plain.txt $@

#doc/es/user-guide/index.html: $(call sw,$(addsuffix /*.txt, doc/es/user-guide))
#	$(rst2html) --stylesheet=../../default.css $(dir $@)index.txt $@
#
#doc/ru/user-guide/index.html: $(call sw,$(addsuffix /*.txt, doc/ru/user-guide))
#	$(rst2html) --stylesheet=../../default.css $(dir $@)index.txt $@
#
doc/en/admin-guide/index-plain.html: $(call sw,$(addsuffix /*.txt, doc/en/admin-guide))
	$(rst2html) --stylesheet=../../default.css $(dir $@)index-plain.txt $@

doc/developers/%.html: doc/developers/%.txt
	$(rst2html) --stylesheet=../default.css $< $@

doc/index.html: doc/index.txt
	$(rst2html) --stylesheet=default.css $< $@

doc/index.%.html: doc/index.%.txt
	$(rst2html) --stylesheet=default.css $< $@

%.html: %.txt
	$(rst2html) --stylesheet=../../default.css $< "$@"

doc/en/release-notes/NEWS.txt: $(NEWS_FILES) tools/generate_release_notes.py
	$(PYTHON) tools/generate_release_notes.py "$@" $(NEWS_FILES)

upgrade_guide_dependencies =  $(call sw,$(addsuffix /*.txt, doc/en/upgrade-guide))

doc/en/upgrade-guide/index.html: $(upgrade_guide_dependencies)
	$(rst2html) --stylesheet=../../default.css $(dir $@)index.txt $@

derived_web_docs = $(htm_files) $(dev_htm_files) 
WEB_DOCS = $(derived_web_docs) $(non_txt_files)
ALL_DOCS = $(derived_web_docs) $(MAN_PAGES)

# the main target to build all the docs
docs-plain: $(ALL_DOCS)

# produce a tree containing just the final docs, ready for uploading to the web
HTMLDIR = html_docs
html-plain: docs-plain
	$(PYTHON) tools/win32/ostools.py copytree $(WEB_DOCS) $(HTMLDIR)

# clean produced docs
clean-plain:
	$(PYTHON) tools/win32/ostools.py remove $(ALL_DOCS) \
	    $(HTMLDIR) $(derived_txt_files)


### Miscellaneous Documentation Targets ###

# build a png of our performance task list
# this is no longer built by default; you can build it if you want to look at it
doc/developers/performance.png: doc/developers/performance.dot
	@echo Generating $@
	@dot -Tpng $< -o$@ || echo "Dot not installed; skipping generation of $@"


### Windows Support ###

# make all the installers completely from scratch, using zc.buildout
# to fetch the dependencies
# These are files that need to be copied into the build location to boostrap
# the build process.
# Note that the path is relative to tools/win32
BUILDOUT_FILES = buildout.cfg \
	buildout-templates/bin/build-installer.bat.in \
	ostools.py bootstrap.py

installer-all:
	@echo Make all the installers from scratch
	@# Build everything in a separate directory, to avoid cluttering the WT
	$(PYTHON) tools/win32/ostools.py makedir build-win32
	@# cd to tools/win32 so that the relative paths are copied correctly
	cd tools/win32 && $(PYTHON) ostools.py copytree $(BUILDOUT_FILES) ../../build-win32
	@# There seems to be a bug in gf.release.brz, It doesn't correctly update
	@# existing release directories, so delete them manually before building
	@# It means things may be rebuilt that don't need to be, but at least
	@# it will be correct when they do.
	cd build-win32 && $(PYTHON) ostools.py remove release */release
	cd build-win32 && $(PYTHON) bootstrap.py
	cd build-win32 && bin/buildout
	cd build-win32 && bin/build-installer.bat $(BRZ_TARGET) $(PLUGIN_TARGET)


clean-installer-all:
	$(PYTHON) tools/win32/ostools.py remove build-win32

# make brz.exe for win32 with py2exe
exe:
	@echo *** Make brz.exe
	$(PYTHON) tools/win32/ostools.py remove breezy/*.pyd
	$(PYTHON) setup.py build_ext -i -f $(PYTHON_BUILDFLAGS)
	$(PYTHON) setup.py py2exe > py2exe.log
	$(PYTHON) tools/win32/ostools.py copytodir tools/win32/start_brz.bat win32_brz.exe
	$(PYTHON) tools/win32/ostools.py copytodir tools/win32/bazaar.url win32_brz.exe

# win32 installer for brz.exe
installer: exe copy-docs
	@echo *** Make Windows installer
	$(PYTHON) tools/win32/run_script.py cog.py -d -o tools/win32/brz.iss tools/win32/brz.iss.cog
	iscc /Q tools/win32/brz.iss

# win32 Python's distutils-based installer
# require to have Python interpreter installed on win32
py-inst-24: docs
	$(PYTHON24) setup.py bdist_wininst --install-script="brz-win32-bdist-postinstall.py" -d .

py-inst-25: docs
	$(PYTHON25) setup.py bdist_wininst --install-script="brz-win32-bdist-postinstall.py" -d .

py-inst-26: docs
	$(PYTHON26) setup.py bdist_wininst --install-script="brz-win32-bdist-postinstall.py" -d .

python-installer: py-inst-24 py-inst-25 py-inst-26


copy-docs: docs
	$(PYTHON) tools/win32/ostools.py copytodir README win32_brz.exe/doc
	$(PYTHON) tools/win32/ostools.py copytree $(WEB_DOCS) win32_brz.exe

# clean on win32 all installer-related files and directories
clean-win32: clean-docs
	$(PYTHON) tools/win32/ostools.py remove build
	$(PYTHON) tools/win32/ostools.py remove win32_brz.exe
	$(PYTHON) tools/win32/ostools.py remove py2exe.log
	$(PYTHON) tools/win32/ostools.py remove tools/win32/brz.iss
	$(PYTHON) tools/win32/ostools.py remove brz-setup*.exe
	$(PYTHON) tools/win32/ostools.py remove brz-*win32.exe
	$(PYTHON) tools/win32/ostools.py remove dist


# i18n targets

.PHONY: update-pot po/brz.pot
update-pot: po/brz.pot

TRANSLATABLE_PYFILES:=$(shell find breezy -name '*.py' \
		| grep -v 'breezy/tests/' \
		| grep -v 'breezy/doc' \
		)

po/brz.pot: $(PYFILES) $(DOCFILES)
	$(PYTHON) ./brz export-pot --include-duplicates > po/brz.pot
	echo $(TRANSLATABLE_PYFILES) | xargs \
	  xgettext --package-name "brz" \
	  --msgid-bugs-address "<bazaar@canonical.com>" \
	  --copyright-holder "Canonical" \
	  --from-code ISO-8859-1 --join --sort-by-file --add-comments=i18n: \
	  -d bzr -p po -o brz.pot


### Packaging Targets ###

.PHONY: dist check-dist-tarball

# build a distribution source tarball
dist: 
	version=`./brz version --short` && \
	echo Building distribution of brz $$version && \
	expbasedir=`mktemp -t -d tmp_brz_dist.XXXXXXXXXX` && \
	expdir=$$expbasedir/brz-$$version && \
	tarball=$$PWD/../brz-$$version.tar.gz && \
	$(MAKE) clean && \
	$(MAKE) && \
	$(PYTHON) setup.py sdist -d $$PWD/.. && \
	gpg --detach-sign --armor $$tarball && \
	rm -rf $$expbasedir

# run all tests in a previously built tarball
check-dist-tarball:
	tmpdir=`mktemp -t -d tmp_brz_check_dist.XXXXXXXXXX` && \
	version=`./brz version --short` && \
	tarball=$$PWD/../brz-$$version.tar.gz && \
	tar Cxz $$tmpdir -f $$tarball && \
	$(MAKE) -C $$tmpdir/brz-$$version check && \
	rm -rf $$tmpdir
