#!/usr/bin/env python3
"""Install the POSIX-oriented Argus tools natively on Windows (no WSL).

nikto, testssl, whatweb, wpscan and phpcs ship as scripts (Perl, bash, Ruby,
PHP) rather than as Windows binaries, so ``where nikto`` finds nothing and the
worker cannot spawn them. Windows also has no shebang handling, and Argus runs
tools as an argv list (``subprocess.Popen`` without ``shell=True``), so a
``.cmd`` wrapper is not enough either: each tool needs a real ``.exe`` on PATH.

This script therefore

* clones/downloads each tool into ``~/.local/share/argus/<tool>`` (or installs
  the gem for wpscan),
* installs the interpreter each one needs (Git-for-Windows Perl/bash, PHP and
  Ruby from winget, when missing),
* compiles a ~6 KB launcher ``~/.local/bin/<tool>.exe`` that forwards argv,
  stdin, stdout and stderr to the interpreter, and
* provides ``hexdump``, which testssl.sh requires and Git-for-Windows omits.

Everything is idempotent: re-running only reports what is already installed.
Use ``--check`` to report status without changing anything.

Not covered: sn1per. It refuses to run as non-root, expects ``/usr/share/sniper``
and services PostgreSQL, so it needs a Linux host (WSL or a container); faking
that on Windows would silently produce a broken scan. Skim it out of scope.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
LOCAL = HOME / ".local"
BIN = LOCAL / "bin"
SHARE = LOCAL / "share" / "argus"



def _git_usr_bin() -> Path:
    """Git-for-Windows' ``usr/bin``, wherever Git is installed.

    ``C:\\Program Files\\Git`` is only the machine-wide default; per-user
    (``%LOCALAPPDATA%\\Programs\\Git``) and Scoop installs live elsewhere, and
    the launchers must point at the interpreter that actually exists.
    """
    git = shutil.which("git")
    if git:
        candidate = Path(git).resolve().parent.parent / "usr" / "bin"
        if (candidate / "bash.exe").is_file() or (candidate / "perl.exe").is_file():
            return candidate
    return Path(r"C:\Program Files\Git\usr\bin")


GIT_USR = _git_usr_bin()
GIT_MINGW = GIT_USR.parent.parent / "mingw64" / "bin"
CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
#: MinGW build of libcurl that Ruby's ffi can load (self-contained; the one in
#: Git-for-Windows needs the whole mingw64 dependency tree and fails to load).
LIBCURL_URL = "https://curl.se/windows/latest.cgi?p=win64-mingw.zip"

PHPCS_VERSION = "4.0.4"
PHPCS_URL = (
    "https://github.com/PHPCSStandards/PHP_CodeSniffer/releases/download/"
    f"{PHPCS_VERSION}/phpcs.phar"
)

#: ``tool -> (github repo, subdirectory that must exist in the checkout)``.
GIT_TOOLS: dict[str, tuple[str, str]] = {
    "nikto": ("sullo/nikto", "program"),
    "testssl": ("testssl/testssl.sh", "testssl.sh"),
    "whatweb": ("urbanadventurer/WhatWeb", "whatweb"),
}

LAUNCHER_TEMPLATE = r"""using System;
using System.Diagnostics;
using System.Text;

class Shim
{
    const string Interpreter = @"__INTERPRETER__";
    const string WorkDir = @"__WORKDIR__";
    static readonly string[] FixedArgs = new string[] { __ARGS__ };
    static readonly string[] ExtraEnv = new string[] { __ENV__ };

    // MSVC/CreateProcess quoting: backslashes are only special before a quote.
    static string Quote(string s)
    {
        if (s.Length == 0) return "\"\"";
        bool needs = false;
        foreach (char c in s) { if (c == ' ' || c == '\t' || c == '"') { needs = true; break; } }
        if (!needs) return s;

        var sb = new StringBuilder("\"");
        int backslashes = 0;
        foreach (char c in s)
        {
            if (c == '\\') { backslashes++; continue; }
            if (c == '"') { sb.Append('\\', backslashes * 2 + 1); sb.Append('"'); backslashes = 0; continue; }
            sb.Append('\\', backslashes); backslashes = 0; sb.Append(c);
        }
        sb.Append('\\', backslashes * 2);
        sb.Append('"');
        return sb.ToString();
    }

    static int Main(string[] args)
    {
        var sb = new StringBuilder();
        foreach (var a in FixedArgs) { if (sb.Length > 0) sb.Append(' '); sb.Append(Quote(a)); }
        foreach (var a in args) { if (sb.Length > 0) sb.Append(' '); sb.Append(Quote(a)); }

        var psi = new ProcessStartInfo(Interpreter);
        psi.Arguments = sb.ToString();
        if (WorkDir.Length > 0) psi.WorkingDirectory = WorkDir;
        psi.UseShellExecute = false;
        foreach (var kv in ExtraEnv)
        {
            if (kv.Length == 0) continue;
            int i = kv.IndexOf('=');
            if (i <= 0) continue;
            string name = kv.Substring(0, i);
            string value = kv.Substring(i + 1);
            // PATH is prepended: the tool still needs the caller's environment
            // (temp dirs, node, ...) but must find its own runtime first.
            string old = psi.EnvironmentVariables[name];
            psi.EnvironmentVariables[name] = name == "PATH" && old != null && old.Length > 0
                ? value + ";" + old
                : value;
        }

        var proc = Process.Start(psi);
        proc.WaitForExit();
        return proc.ExitCode;
    }
}
"""

#: minimal hexdump(1) supporting the two idioms testssl.sh uses:
#: ``-e 'N/1 "%02X"'`` and ``-C``. Git-for-Windows ships od/xxd but no hexdump.
HEXDUMP_PERL = r"""#!/usr/bin/perl
# hexdump(1) replacement for hosts without util-linux (Windows / Git-Bash).
use strict;
use warnings;

my $canonical = 0;
my @formats;
my ( $skip, $length, $file ) = ( 0, undef, undef );
while ( defined( my $arg = shift @ARGV ) ) {
    if    ( $arg eq '-v' ) { next }
    elsif ( $arg eq '-C' ) { $canonical = 1 }
    elsif ( $arg eq '-e' ) { push @formats, shift @ARGV }
    elsif ( $arg eq '-n' ) { $length    = shift @ARGV }
    elsif ( $arg eq '-s' ) { $skip      = shift @ARGV }
    elsif ( $arg =~ /^-/ ) { die "hexdump: unsupported option $arg\n" }
    else                   { $file = $arg }
}
die "hexdump: no format specified\n" unless $canonical || @formats;

my $data = '';
if ( defined $file ) {
    open my $fh, '<:raw', $file or die "hexdump: $file: $!\n";
    binmode $fh;
    local $/;
    $data = <$fh>;
} else {
    binmode STDIN;
    local $/;
    $data = <STDIN>;
}
$data = '' unless defined $data;
$data = substr( $data, $skip ) if $skip;
$data = substr( $data, 0, $length ) if $length;

if ($canonical) {
    my $offset = $skip || 0;
    while ( length $data ) {
        my $chunk = substr( $data, 0, 16, '' );
        my @hex = map { sprintf '%02x', ord } split //, $chunk;
        my $last = $#hex;
        my $hex  = join ' ', @hex[ 0 .. ( $last < 7 ? $last : 7 ) ];
        $hex .= '  ' . join ' ', @hex[ 8 .. $last ] if $last > 7;
        $hex = sprintf '%-49s', $hex;
        my $ascii = join '', map { $_ =~ /[\x20-\x7e]/ ? $_ : '.' } split //, $chunk;
        printf "%08x  %s |%s|\n", $offset, $hex, $ascii;
        $offset += length $chunk;
    }
    printf "%08x\n", $offset;
    exit 0;
}

my @specs = map {
    my $f = $_;
    $f =~ s/^\s+|\s+$//g;
    my ( $count, $size, $fmt ) = $f =~ m{^\s*(\d+)\s*/\s*(\d+)\s+"([^"]*)"\s*$}
        or die "hexdump: unsupported format $f\n";
    { per_line => $count, size => $size, fmt => $fmt };
} @formats;

while ( length $data ) {
    my $chunk = substr( $data, 0, $specs[0]{per_line}, '' );
    my $line  = '';
    for my $i ( 0 .. length( $chunk ) - 1 ) {
        for my $spec (@specs) {
            next if $spec->{size} != 1;
            $line .= sprintf $spec->{fmt}, ord( substr( $chunk, $i, 1 ) );
        }
    }
    print "$line\n";
}
exit 0;
"""


def log(message: str) -> None:
    print(f"[portable-tools] {message}", flush=True)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)  # noqa: S603


def have(binary: str) -> str | None:
    """Resolve *binary* on PATH, preferring a real executable over a .bat shim."""
    return shutil.which(binary)


def posix_path(path: Path | str) -> str:
    """Convert ``C:\\x\\y`` to ``/c/x/y`` for MSYS/Cygwin interpreters."""
    text = str(path).replace("\\", "/")
    if len(text) > 1 and text[1] == ":":
        text = "/" + text[0].lower() + text[2:]
    return text


def install_from_winget(package: str) -> bool:
    if not have("winget"):
        log(f"FAIL {package}: winget is not available")
        return False
    log(f"installing {package} with winget (this can take a few minutes) ...")
    result = run(
        [
            "winget", "install", "--id", package, "-e", "--silent",
            "--accept-package-agreements", "--accept-source-agreements",
        ],
        timeout=1800,
    )
    if result.returncode != 0:
        log(f"FAIL {package}: {result.stdout[-300:]}{result.stderr[-300:]}")
        return False
    return True


#: ``--check`` must not touch the system: the ensure_* helpers consult it.
CHECK_ONLY = False


def ensure_php() -> str | None:
    php = have("php")
    if php:
        return php
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for candidate in sorted(packages.glob("PHP.PHP.NTS.*/php.exe"), reverse=True):
        return str(candidate)
    if CHECK_ONLY:
        log("MISSING php: no PHP runtime (winget install PHP.PHP.NTS.8.4)")
        return None
    install_from_winget("PHP.PHP.NTS.8.4")
    for candidate in sorted(packages.glob("PHP.PHP.NTS.*/php.exe"), reverse=True):
        return str(candidate)
    return None


def ensure_ruby() -> str | None:
    ruby = have("ruby")
    if ruby:
        return ruby
    for candidate in (Path(r"C:\Ruby33-x64\bin\ruby.exe"), Path(r"C:\Ruby34-x64\bin\ruby.exe")):
        if candidate.is_file():
            return str(candidate)
    if CHECK_ONLY:
        log("MISSING ruby: no Ruby toolchain (winget install RubyInstallerTeam.RubyWithDevKit.3.3)")
        return None
    install_from_winget("RubyInstallerTeam.RubyWithDevKit.3.3")
    for candidate in (Path(r"C:\Ruby33-x64\bin\ruby.exe"), Path(r"C:\Ruby34-x64\bin\ruby.exe")):
        if candidate.is_file():
            return str(candidate)
    return None


def git_clone(repo: str, dest: Path) -> bool:
    if dest.exists() and any(dest.iterdir()):
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"cloning github.com/{repo} ...")
    result = run(["git", "clone", "--depth", "1", f"https://github.com/{repo}.git", str(dest)], timeout=600)
    if result.returncode != 0:
        log(f"FAIL clone {repo}: {result.stderr[-300:]}")
        return False
    return True


def download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"downloading {url}")
    try:
        with urllib.request.urlopen(url, timeout=300) as response:  # noqa: S310
            dest.write_bytes(response.read())
        return True
    except Exception as error:  # noqa: BLE001 - surfaced to the user below
        log(f"FAIL download {url}: {error}")
        return False


def build_launcher(name: str, interpreter: str, workdir: Path | None,
                   args: list[str], env: list[str]) -> bool:
    """Compile ``~/.local/bin/<name>.exe`` around *interpreter*."""
    if not CSC.is_file():
        log(f"FAIL {name}: {CSC} not found (.NET Framework 4 is required)")
        return False
    source = LAUNCHER_TEMPLATE
    source = source.replace("__INTERPRETER__", interpreter.replace('"', '""'))
    source = source.replace("__WORKDIR__", str(workdir or "").replace('"', '""'))
    source = source.replace("__ARGS__", ", ".join("@" + json.dumps(a) for a in args))
    source = source.replace("__ENV__", ", ".join("@" + json.dumps(e) for e in env))

    build_dir = SHARE / "launchers"
    build_dir.mkdir(parents=True, exist_ok=True)
    cs_file = build_dir / f"{name}.cs"
    cs_file.write_text(source, encoding="utf-8")
    out = BIN / f"{name}.exe"
    BIN.mkdir(parents=True, exist_ok=True)
    result = run([str(CSC), "/nologo", "/target:exe", "/optimize+", "/platform:anycpu",
                  "/r:System.dll", f"/out:{out}", str(cs_file)], timeout=300)
    if result.returncode != 0:
        log(f"FAIL {name}: csc: {result.stdout[-300:]}{result.stderr[-300:]}")
        return False
    log(f"OK {name}: launcher {out}")
    return True


def launcher_paths(*extra: Path) -> list[str]:
    """PATH prefix the launchers hand to their interpreter.

    Includes the MinGW runtime directories: testssl needs bash's `openssl`,
    sed, awk and the hexdump shim next to each other.
    """
    parts = [BIN, GIT_USR, GIT_MINGW, *extra]
    return ["PATH=" + ";".join(str(p) for p in parts if p)]


def ensure_perl_lib() -> bool:
    """Install XML::Writer, the one CPAN module nikto refuses to start without."""
    lib = SHARE / "perl-lib"
    module = lib / "XML" / "Writer.pm"
    if module.is_file():
        log("OK perl-lib: XML::Writer present")
        return True
    try:
        with urllib.request.urlopen("https://fastapi.metacpan.org/v1/release/XML-Writer", timeout=120) as response:  # noqa: S310
            meta = json.loads(response.read())
        url = meta["download_url"]
    except Exception as error:  # noqa: BLE001 - reported, nikto still runs without XML output
        log(f"FAIL perl-lib: cannot resolve XML::Writer on MetaCPAN: {error}")
        return False
    archive = SHARE / "XML-Writer.tar.gz"
    if not download(url, archive):
        return False
    import tarfile
    with tarfile.open(archive) as bundle:  # noqa: S202 - trusted CPAN tarball
        for member in bundle.getmembers():
            if member.name.endswith("lib/XML/Writer.pm"):
                source = bundle.extractfile(member)
                module.parent.mkdir(parents=True, exist_ok=True)
                module.write_bytes(source.read())
                break
    archive.unlink(missing_ok=True)
    log(f"OK perl-lib: XML::Writer at {module}")
    return module.is_file()


def ensure_hexdump() -> None:
    target = BIN / "hexdump"
    if have("hexdump"):
        log("OK hexdump: already on PATH")
        return
    BIN.mkdir(parents=True, exist_ok=True)
    target.write_text(HEXDUMP_PERL, encoding="utf-8", newline="\n")
    log(f"OK hexdump: shim at {target}")


def launcher(name: str) -> Path:
    """The ``.exe`` Argus actually spawns for *name*.

    Presence of the checkout is not enough: Argus runs ``[exe, ...]``, so a tool
    whose launcher is missing does not work even though its sources are there.
    """
    return BIN / f"{name}.exe"


def report(name: str, ok: bool, detail: Path | str) -> bool:
    log(f"{'OK' if ok else 'MISSING'} {name}: {detail}")
    return ok


def install_nikto(check: bool) -> bool:
    checkout = SHARE / "nikto"
    entry = checkout / "program" / "nikto.pl"
    conf = checkout / "nikto.conf"
    exe = launcher("nikto")
    if check:
        return report("nikto", entry.is_file() and conf.is_file() and exe.is_file(),
                      exe if exe.is_file() else checkout)
    if not entry.is_file() and not git_clone("sullo/nikto", checkout):
        return False
    if not entry.is_file():
        log(f"FAIL nikto: {entry} missing from the checkout")
        return False
    if not conf.is_file():
        shutil.copy(checkout / "program" / "nikto.conf.default", conf)
        log(f"OK nikto: wrote {conf}")
    ensure_perl_lib()
    if exe.is_file():
        return report("nikto", True, exe)
    perl = GIT_USR / "perl.exe"
    if not perl.is_file():
        log("FAIL nikto: Git-for-Windows perl.exe not found at " + str(perl))
        return False
    return build_launcher(
        "nikto", str(perl), checkout,
        [f"-I{posix_path(SHARE / 'perl-lib')}", posix_path(entry)],
        launcher_paths(),
    )


def install_testssl(check: bool) -> bool:
    checkout = SHARE / "testssl"
    entry = checkout / "testssl.sh"
    exe = launcher("testssl")
    if check:
        return report("testssl", entry.is_file() and exe.is_file(),
                      exe if exe.is_file() else checkout)
    if not entry.is_file() and not git_clone("testssl/testssl.sh", checkout):
        return False
    if not entry.is_file():
        log(f"FAIL testssl: {entry} missing from the checkout")
        return False
    ensure_hexdump()
    if exe.is_file():
        return report("testssl", True, exe)
    bash = GIT_USR / "bash.exe"
    if not bash.is_file():
        log("FAIL testssl: Git-for-Windows bash.exe not found at " + str(bash))
        return False
    return build_launcher("testssl", str(bash), checkout, [posix_path(entry)], launcher_paths())


def install_whatweb(check: bool) -> bool:
    checkout = SHARE / "whatweb"
    entry = checkout / "whatweb"
    exe = launcher("whatweb")
    if check:
        return report("whatweb", entry.is_file() and exe.is_file(),
                      exe if exe.is_file() else checkout)
    ruby = ensure_ruby()
    if not ruby:
        log("FAIL whatweb: no Ruby runtime (winget install RubyInstallerTeam.RubyWithDevKit.3.3)")
        return False
    if not entry.is_file() and not git_clone("urbanadventurer/WhatWeb", checkout):
        return False
    if not entry.is_file():
        log(f"FAIL whatweb: {entry} missing from the checkout")
        return False
    if exe.is_file():
        return report("whatweb", True, exe)
    gem = str(Path(ruby).with_name("gem.cmd"))
    result = run([gem, "install", "addressable", "--no-document"], timeout=600)
    if result.returncode != 0:
        log(f"FAIL whatweb: gem install addressable: {result.stdout[-300:]}")
        return False
    return build_launcher("whatweb", ruby, checkout, [str(entry)], launcher_paths(Path(ruby).parent))


def install_wpscan(check: bool) -> bool:
    ruby = ensure_ruby()
    if not ruby:
        log("FAIL wpscan: no Ruby runtime (winget install RubyInstallerTeam.RubyWithDevKit.3.3)")
        return False
    ruby_dir = Path(ruby).parent
    bin_stub = Path(ruby).with_name("wpscan")
    exe = launcher("wpscan")
    if check:
        ok = bin_stub.is_file() and exe.is_file() and (ruby_dir / "libcurl.dll").is_file()
        return report("wpscan", ok, exe if exe.is_file() else bin_stub)
    if not bin_stub.is_file():
        gem = str(Path(ruby).with_name("gem.cmd"))
        log("installing the wpscan gem (nokogiri etc., a few minutes) ...")
        result = run([gem, "install", "wpscan", "--no-document"], timeout=1800)
        if result.returncode != 0:
            log(f"FAIL wpscan: gem install: {result.stdout[-300:]}{result.stderr[-300:]}")
            return False

    # wpscan's HTTP layer (typhoeus/ethon/ffi) dlopen()s "libcurl" with
    # LOAD_WITH_ALTERED_SEARCH_PATH, which ignores PATH: the DLL has to sit
    # next to ruby.exe. Git's libcurl needs the whole mingw64 tree, so use the
    # self-contained curl-for-win build instead.
    if not (ruby_dir / "libcurl.dll").is_file():
        archive = SHARE / "curl-win.zip"
        if not download(LIBCURL_URL, archive):
            return False
        import zipfile
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                if member.endswith("libcurl-x64.dll"):
                    bundle.extract(member, SHARE / "curl-win")
                    shutil.copy(SHARE / "curl-win" / member, ruby_dir / "libcurl.dll")
                    break
        archive.unlink(missing_ok=True)
        log(f"OK wpscan: libcurl.dll installed next to {ruby_dir}")

    if exe.is_file():
        return report("wpscan", True, exe)
    return build_launcher("wpscan", ruby, None, [str(bin_stub)], launcher_paths(ruby_dir))


def install_phpcs(check: bool) -> bool:
    phar = SHARE / "phpcs" / "phpcs.phar"
    exe = launcher("phpcs")
    if check:
        return report("phpcs", phar.is_file() and exe.is_file(), exe if exe.is_file() else phar)
    php = ensure_php()
    if not php:
        log("FAIL phpcs: no PHP runtime (winget install PHP.PHP.NTS.8.4)")
        return False
    if not phar.is_file() and not download(PHPCS_URL, phar):
        return False
    if exe.is_file():
        return report("phpcs", True, exe)
    return build_launcher("phpcs", php, None, [str(phar)], launcher_paths())


TOOLS = {
    "nikto": install_nikto,
    "testssl": install_testssl,
    "whatweb": install_whatweb,
    "wpscan": install_wpscan,
    "phpcs": install_phpcs,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Argus' script-based tools natively on Windows.")
    parser.add_argument("--check", action="store_true", help="report status, install nothing")
    parser.add_argument("tools", nargs="*", choices=list(TOOLS), help="subset to install (default: all)")
    options = parser.parse_args(argv)

    global CHECK_ONLY
    CHECK_ONLY = options.check
    if os.name != "nt":
        log("this installer is for Windows; use scripts/argus-setup.sh elsewhere")
        return 2
    if not CSC.is_file():
        log(f"FAIL: .NET Framework 4 compiler not found at {CSC} — launchers cannot be built")
        return 1

    selected = options.tools or list(TOOLS)
    failures = [name for name in selected if not TOOLS[name](options.check)]
    if failures:
        log("incomplete: " + ", ".join(failures))
        return 1
    log("done: " + ", ".join(selected))
    return 0


if __name__ == "__main__":
    sys.exit(main())
