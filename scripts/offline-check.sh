#!/usr/bin/env bash
# The offline check: proves the app runs with no way out of its network
# (docs/offline.md; openspec self-hosting-setup design decision 16).
#
#   scripts/offline-check.sh [--no-build] [-f extra.yml ...]
#
# It builds the app's images (this needs the internet), then starts the app in
# demo mode on a compose network marked internal, with a stand-in model server
# on that network, without building or pulling anything more. A smoke test
# inside the network then runs seven steps and prints each one. The exit
# status is 0 only when every step passes; otherwise it is 1 and the output
# names the step that failed. The containers and their data are removed when
# it ends, also on failure or Ctrl-C.
#
# --no-build  uses the images already built (focus-funnel-backend and
#             focus-funnel-frontend, tag FOCUS_FUNNEL_TAG or local).
# -f FILE     adds a compose file after the check's own, for every call.
#
# It never reads the project's .env: every compose call reads
# deploy/offline/check/check.env instead, and the check's overlay writes out
# the settings it uses.

set -euo pipefail

usage() {
	echo "Usage: scripts/offline-check.sh [--no-build] [-f extra.yml ...]"
}

fail() {
	echo "offline-check: $*" >&2
	exit 2
}

root=$(cd "$(dirname "$0")/.." && pwd)
build=1
files=(-f "$root/docker-compose.yml" -f "$root/docker-compose.offline-check.yml")
while [ $# -gt 0 ]; do
	case $1 in
	--no-build)
		build=0
		shift
		;;
	-f | --file)
		[ $# -ge 2 ] || fail "$1 needs a compose file"
		[ -f "$2" ] || fail "no such compose file: $2"
		files+=(-f "$(cd "$(dirname "$2")" && pwd)/$(basename "$2")")
		shift 2
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		usage >&2
		fail "unknown argument: $1"
		;;
	esac
done
[ "${OFFLINE_CHECK_NO_BUILD:-}" = 1 ] && build=0

project=ff-offline-check
compose() {
	docker compose -p "$project" --project-directory "$root" \
		--env-file "$root/deploy/offline/check/check.env" "${files[@]}" "$@"
}

if [ "$build" = 1 ]; then
	echo "offline-check: building the images (online)"
	compose build backend frontend
fi

cleanup() {
	echo "offline-check: removing the check's containers and data"
	compose --profile smoke down --volumes --remove-orphans --timeout 5 >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

echo "offline-check: starting the services, with no build or pull"
if ! compose up -d --no-build --pull never; then
	echo "offline-check: could not start the services. Build the images first:" >&2
	echo "  docker compose build   (or run this script without --no-build)" >&2
	exit 1
fi

status=0
compose run --rm --no-deps smoke || status=$?
if [ "$status" -ne 0 ]; then
	echo "offline-check: FAILED (exit $status). The last lines of the services' logs:" >&2
	compose logs --no-color --tail 20 backend frontend stub-provider >&2 || true
	exit 1
fi
echo "offline-check: passed"
