#!/bin/sh
# HSTN release bootstrap. Keep the complete body in a function for piped use.
main() (
    set -eu
    release_version=${HSTN_VERSION:-}
    release_base=${HSTN_RELEASE_BASE_URL:-}
    archive=
    checksum=
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --version|--release-base-url|--archive|--sha256)
                [ "$#" -ge 2 ] || { echo "HSTN: $1 requires a value" >&2; exit 2; }
                case "$1" in
                    --version) release_version=$2 ;;
                    --release-base-url) release_base=$2 ;;
                    --archive) archive=$2 ;;
                    --sha256) checksum=$2 ;;
                esac
                shift 2 ;;
            --) shift; break ;;
            *) break ;;
        esac
    done
    command -v python3 >/dev/null 2>&1 || { echo 'HSTN: Python 3.10+ is required' >&2; exit 1; }
    python3 -c 'import sys; sys.exit(sys.version_info < (3,10))' || { echo 'HSTN: Python 3.10+ is required' >&2; exit 1; }
    # Extracted source/release archives need no network connection.
    if [ -z "$archive" ] && [ -f "$0" ]; then
        script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
        if [ -f "$script_dir/install.py" ] && [ -f "$script_dir/../VERSION" ]; then
            exec python3 -B "$script_dir/install.py" "$@"
        fi
    fi
    work=$(mktemp -d "${TMPDIR:-/tmp}/hstn-download.XXXXXXXX")
    trap 'rm -rf -- "$work"' 0
    trap 'exit 130' 1 2 3 15
    if [ -z "$archive" ]; then
        [ -n "$release_base" ] && [ -n "$release_version" ] || {
            echo 'HSTN: supply --release-base-url HTTPS_URL --version VERSION (public hosting is not configured yet)' >&2
            exit 2
        }
        python3 - "$release_base" "$release_version" <<'PY'
import re, sys
from urllib.parse import urlsplit
url = urlsplit(sys.argv[1])
if (url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment
        or any(c.isspace() for c in sys.argv[1]) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9]+)*', sys.argv[2])):
    sys.exit('HSTN: invalid HTTPS release base URL or version')
PY
        command -v curl >/dev/null 2>&1 || { echo 'HSTN: curl is required for downloading' >&2; exit 1; }
        archive="$work/hstn-$release_version.tar.gz"
        url="${release_base%/}/v$release_version"
        curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fSL --retry 2 --connect-timeout 15 --max-time 300 -o "$archive" "$url/hstn-$release_version.tar.gz"
        curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fSL --retry 2 --connect-timeout 15 --max-time 60 -o "$work/SHA256SUMS" "$url/SHA256SUMS"
        checksum=$(python3 - "$work/SHA256SUMS" "hstn-$release_version.tar.gz" <<'PY'
import re, sys
from pathlib import Path
matches = []
for line in Path(sys.argv[1]).read_text().splitlines():
    fields = line.split()
    if len(fields) == 2 and fields[1].lstrip('*') == sys.argv[2] and re.fullmatch('[0-9a-fA-F]{64}', fields[0]):
        matches.append(fields[0])
if len(matches) != 1:
    sys.exit('HSTN: missing or ambiguous release checksum')
print(matches[0])
PY
        )
    fi
    [ -n "$checksum" ] || { echo 'HSTN: offline --archive requires --sha256 HEX_DIGEST' >&2; exit 2; }
    python3 -B - "$archive" "$checksum" "$work" "$release_version" "$@" <<'PY'
import hashlib, os, re, subprocess, sys, tarfile
from pathlib import Path, PurePosixPath
archive, digest, work, requested = sys.argv[1:5]
if not re.fullmatch('[0-9a-fA-F]{64}', digest):
    sys.exit('HSTN: invalid checksum')
with open(archive, 'rb') as stream:
    computed = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        computed.update(chunk)
if computed.hexdigest() != digest.lower():
    sys.exit('HSTN: archive checksum mismatch; nothing executed')
try:
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        names = set()
        total = 0
        roots = set()
        for entry in members:
            path = PurePosixPath(entry.name)
            if (path.is_absolute() or '..' in path.parts or str(path) != entry.name
                    or not entry.isfile() or entry.mode & 0o7000 or entry.name in names
                    or len(path.parts) < 2 or not re.fullmatch(r'hstn-[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9]+)*', path.parts[0])):
                raise ValueError('unsafe archive member: ' + entry.name)
            names.add(entry.name)
            roots.add(path.parts[0])
            total += entry.size
            if total > 256 * 1024 * 1024 or len(names) > 4096:
                raise ValueError('archive exceeds release limits')
        if len(roots) != 1:
            raise ValueError('archive must contain one release')
        release_name = next(iter(roots))
        if requested and release_name != 'hstn-' + requested:
            raise ValueError('archive version does not match requested version')
        for entry in members:
            target = Path(work)/'release'/entry.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(entry) as incoming, target.open('xb') as outgoing:
                while True:
                    chunk = incoming.read(1024 * 1024)
                    if not chunk:
                        break
                    outgoing.write(chunk)
            target.chmod(entry.mode & 0o777)
    release = Path(work)/'release'/release_name
    if (release/'VERSION').read_text().strip() != release_name[len('hstn-'):]:
        raise ValueError('release VERSION mismatch')
    if not (release/'installer/install.py').is_file():
        raise ValueError('release installer missing')
except (OSError, ValueError, tarfile.TarError) as error:
    sys.exit('HSTN: invalid release: ' + str(error))
sys.exit(subprocess.call([sys.executable, '-B', str(release/'installer/install.py'), *sys.argv[5:]]))
PY
)
main "$@"
