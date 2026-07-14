#!/usr/bin/env bash
#
# reset_data.sh — delete DB, recordings and logs after confirmation.
#
# Removes the CONTENTS of data/db, data/recordings and data/logs but keeps the
# directories themselves and data/.gitkeep. Refuses to touch anything outside
# the repo's data/ tree.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

DATA_DIR="${REPO_ROOT}/data"

echo "This will permanently delete the contents of:"
echo "    ${DATA_DIR}/db"
echo "    ${DATA_DIR}/recordings"
echo "    ${DATA_DIR}/logs"
echo "(directories and data/.gitkeep are kept)"
echo ""

read -r -p "Proceed? [y/N] " reply
case "${reply}" in
  y|Y|yes|YES) ;;
  *) echo "Aborted. Nothing deleted."; exit 0 ;;
esac

# Safety: only operate on subdirectories we expect, all under DATA_DIR.
for sub in db recordings logs; do
  target="${DATA_DIR}/${sub}"
  # Guard: target must be inside DATA_DIR and a directory.
  case "${target}" in
    "${DATA_DIR}/"*) ;;
    *) echo "Refusing to touch ${target} (outside data/)"; exit 1 ;;
  esac
  if [ -d "${target}" ]; then
    # Delete contents including dotfiles, but keep the directory.
    find "${target}" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
    echo "Cleared ${target}"
  else
    mkdir -p "${target}"
    echo "Recreated ${target}"
  fi
done

# Ensure the top-level marker survives.
[ -f "${DATA_DIR}/.gitkeep" ] || : > "${DATA_DIR}/.gitkeep"

echo "Done. data/ reset."
