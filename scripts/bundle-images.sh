#!/usr/bin/env bash
# Builds the app's images, pulls the other images an install uses, and saves
# them all into one archive for a host with no internet (docs/offline.md).
#
#   scripts/bundle-images.sh [-f overlay.yml ...]
#
# It always uses docker-compose.yml. Without -f it adds the overlays of an
# offline install: docker-compose.offline.yml and docker-compose.pocket-id.yml.
# With -f it adds the overlays named instead (repeat -f for each one).
#
# Writes focus-funnel-images-<tag>.tar.gz and its .sha256 in the repository
# root, where <tag> is FOCUS_FUNNEL_TAG (default: local). On the offline host:
#
#   sha256sum -c focus-funnel-images-<tag>.tar.gz.sha256
#   gunzip -c focus-funnel-images-<tag>.tar.gz | docker load
#   docker compose <the same -f files> up -d --no-build --pull never
#
# It needs no .env: every compose command reads a generated placeholder file
# instead, so the Pocket ID overlay's required POCKET_ID_ENCRYPTION_KEY does
# not stop it. The placeholder is used only to read the compose files and
# never reaches an image.

set -euo pipefail

usage() {
	echo "Usage: scripts/bundle-images.sh [-f overlay.yml ...]"
}

fail() {
	echo "bundle-images: $*" >&2
	exit 2
}

root=$(cd "$(dirname "$0")/.." && pwd)
overlays=()
while [ $# -gt 0 ]; do
	case $1 in
	-f | --file)
		[ $# -ge 2 ] || fail "$1 needs a compose file"
		overlays+=("$2")
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
if [ ${#overlays[@]} -eq 0 ]; then
	overlays=("$root/docker-compose.offline.yml" "$root/docker-compose.pocket-id.yml")
fi

files=(-f "$root/docker-compose.yml")
for overlay in "${overlays[@]}"; do
	[ -f "$overlay" ] || fail "no such compose file: $overlay"
	files+=(-f "$overlay")
done

tag=${FOCUS_FUNNEL_TAG:-local}
case $tag in
*[!A-Za-z0-9_.-]* | '') fail "FOCUS_FUNNEL_TAG must be letters, digits, '.', '_', or '-', not \"$tag\"" ;;
esac
archive="focus-funnel-images-$tag.tar.gz"

placeholder=$(mktemp "${TMPDIR:-/tmp}/bundle-images-env.XXXXXX")
partial="$root/.$archive.partial"
trap 'rm -f "$placeholder" "$partial"' EXIT
trap 'exit 1' HUP INT TERM
{
	echo "POCKET_ID_ENCRYPTION_KEY=placeholder-for-bundling"
	echo "FOCUS_FUNNEL_TAG=$tag"
} >"$placeholder"

compose() {
	docker compose --env-file "$placeholder" "${files[@]}" "$@"
}

echo "bundle-images: building the app's images (tag $tag)"
compose build
echo "bundle-images: pulling the other images"
compose pull --ignore-buildable

images=$(compose config --images | sort -u)
[ -n "$images" ] || fail "the compose files name no images"
echo "bundle-images: saving these images:"
echo "$images" | sed 's/^/  /'

# shellcheck disable=SC2086 # one image name per word
docker save $images | gzip >"$partial"
mv "$partial" "$root/$archive"
(cd "$root" && sha256sum "$archive" >"$archive.sha256")

echo "bundle-images: wrote $archive and $archive.sha256 in $root"
echo "bundle-images: copy both, the checkout, and .data/ollama (with its models) to the offline host."
