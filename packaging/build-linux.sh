#!/usr/bin/env bash
# Build the Linux app inside a manylinux_2_28 container (glibc 2.28), so the result runs on old distros.
# A PyInstaller bundle needs a glibc as new as the newest symbol in anything it contains, and building on a
# current runner would bundle that runner's libstdc++ and compile tinysoundfont against its glibc.
#
# CI runs:  docker run --rm -v "$PWD:/work" -w /work quay.io/pypa/manylinux_2_28_x86_64 bash packaging/build-linux.sh
set -euo pipefail

LIMIT=2.28

# uv fetches python-build-standalone, a shared-library CPython (PyInstaller needs one; manylinux's own Pythons are static).
/opt/python/cp312-cp312/bin/python -m pip install --quiet uv
/opt/python/cp312-cp312/bin/uv venv --python 3.14 --managed-python --seed /tmp/venv
# shellcheck disable=SC1091
source /tmp/venv/bin/activate

python -m pip install --quiet -r requirements.txt pyinstaller pillow
# No wheel for this Python: it builds from source here, against the container's old glibc.
python -m pip install --no-deps tinysoundfont || echo "No tinysoundfont for this platform: MIDI title music is left out"

python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/CouchDoom.spec

echo "--- glibc floor (limit $LIMIT)"
worst=0
over=()
while IFS= read -r f; do
    v=$(objdump -T "$f" 2>/dev/null | grep -o 'GLIBC_[0-9.]*' | sed 's/GLIBC_//' | sort -V | tail -1 || true)
    [ -z "$v" ] && continue
    if [ "$(printf '%s\n%s\n' "$v" "$worst" | sort -V | tail -1)" = "$v" ]; then worst=$v; fi
    if [ "$(printf '%s\n%s\n' "$v" "$LIMIT" | sort -V | tail -1)" != "$LIMIT" ]; then over+=("$v  $f"); fi
done < <(find dist -type f \( -name '*.so*' -o -name CouchDoom \))
echo "Newest glibc symbol the build needs: $worst"
if [ "${#over[@]}" -gt 0 ]; then
    echo "Files needing more than $LIMIT:" >&2
    printf '  %s\n' "${over[@]}" >&2
    exit 1
fi
