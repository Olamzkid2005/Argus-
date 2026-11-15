#!/usr/bin/env bash
# Install Nikto into .livefire without root.
#
# Nikto is the one well-known web scanner that actually exercises classic
# SQLi/XSS/LFI checks on an old-fashioned PHP/ASP site, which is exactly what a
# public demo target is. It is a Perl program with one non-core dependency
# (XML::Writer), so it installs unprivileged: the tarball goes under
# .livefire/tools/nikto, XML::Writer under .livefire/tools/perl-lib, and
# .livefire/bin/nikto is a wrapper that puts that lib on PERL5LIB.
#
# Usage: bash scripts/livefire/install-nikto.sh
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOLS="$REPO/.livefire/tools"
BIN="$REPO/.livefire/bin"
mkdir -p "$TOOLS" "$BIN" "$TOOLS/perl-lib/XML"

if [ ! -f "$TOOLS/nikto/program/nikto.pl" ]; then
  curl -sL -o /tmp/nikto.tar.gz https://github.com/sullo/nikto/archive/refs/heads/master.tar.gz
  mkdir -p "$TOOLS/nikto"
  tar xzf /tmp/nikto.tar.gz -C /tmp
  cp -r /tmp/nikto-main/. "$TOOLS/nikto/"
fi

if [ ! -f "$TOOLS/perl-lib/XML/Writer.pm" ]; then
  curl -sL -o /tmp/xmlwriter.tar.gz https://cpan.metacpan.org/authors/id/J/JO/JOSEPHW/XML-Writer-0.900.tar.gz
  tar xzf /tmp/xmlwriter.tar.gz -C /tmp
  cp /tmp/XML-Writer-0.900/Writer.pm "$TOOLS/perl-lib/XML/Writer.pm"
fi

chmod +x "$TOOLS/nikto/program/nikto.pl"
printf '%s\n' '#!/bin/sh' '# Nikto needs XML::Writer, which the system perl does not have; ship it with us.' \
  'REPO="$(cd "$(dirname "$0")/../.." && pwd)"' \
  'PERL5LIB="$REPO/.livefire/tools/perl-lib${PERL5LIB:+:$PERL5LIB}" \' \
  '  exec perl "$REPO/.livefire/tools/nikto/program/nikto.pl" "$@"' > "$BIN/nikto"
chmod +x "$BIN/nikto"
"$BIN/nikto" -Version 2>/dev/null | head -1
