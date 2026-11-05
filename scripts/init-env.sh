#!/bin/sh
# Creates .env from .env.example, or completes an existing .env, with new
# random bootstrap secrets. It never changes a value that is set.
#
#   scripts/init-env.sh [--auth-mode oidc|firebase|demo]
#
# Without .env it copies .env.example and sets KEY_ENCRYPTION_KEY,
# SESSION_SECRET, POCKET_ID_ENCRYPTION_KEY, and a new POSTGRES_PASSWORD with a
# DATABASE_URL that uses it. With .env it fills only those of
# KEY_ENCRYPTION_KEY, SESSION_SECRET, and POCKET_ID_ENCRYPTION_KEY that are
# empty, and never touches POSTGRES_PASSWORD or DATABASE_URL. --auth-mode sets
# AUTH_MODE only when it is empty. It prints the names it set, never the values.
#
# POSIX sh and POSIX sed only, so it runs with GNU tools and with BusyBox.
# See docs/setup.md.

set -eu
# No pathname expansion: the sed expressions below are split on spaces and
# hold "*" and "[".
set -f
umask 077

usage() {
	echo "Usage: scripts/init-env.sh [--auth-mode oidc|firebase|demo]"
}

fail() {
	echo "init-env: $*" >&2
	exit 2
}

mode=
while [ $# -gt 0 ]; do
	case $1 in
	--auth-mode)
		[ $# -ge 2 ] || fail "--auth-mode needs a value: oidc, firebase, or demo"
		mode=$2
		shift 2
		;;
	--auth-mode=*)
		mode=${1#--auth-mode=}
		shift
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

case $mode in
'' | oidc | firebase | demo) ;;
*) fail "--auth-mode must be oidc, firebase, or demo, not \"$mode\"" ;;
esac

root=$(cd "$(dirname "$0")/.." && pwd)
env_file=$root/.env
example=$root/.env.example
pg_data=$root/.data/postgres

command -v openssl >/dev/null 2>&1 || fail "openssl is needed to generate the secrets"

if [ -f "$env_file" ]; then
	creating=false
	source_file=$env_file
else
	[ -f "$example" ] || fail "no .env and no .env.example in $root"
	creating=true
	source_file=$example
fi

# The value of the last NAME= line, or nothing.
value_of() {
	sed -n "s/^$1=//p" "$source_file" | tail -n 1 | tr -d ' \t'
}

has_line() {
	grep -q "^$1=" "$source_file"
}

is_empty() {
	[ -z "$(value_of "$1")" ]
}

# The secrets exist only in this file until it is moved into place. It sits
# next to .env (never in /tmp), and the traps remove it on any exit, also
# when the script is stopped with Ctrl+C or a TERM signal.
tmp=
trap 'rm -f "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
tmp=$(mktemp "$root/.env.tmp.XXXXXX")

sed_args=
appends=
filled=

# Fill NAME with VALUE when it is empty. VALUE is base64 or hex, so it holds
# no "|", "&", or "\".
fill() {
	if has_line "$1"; then
		sed_args="$sed_args -e s|^$1=[[:space:]]*\$|$1=$2|"
	else
		appends="$appends $1=$2"
	fi
	filled="$filled $1"
}

if is_empty KEY_ENCRYPTION_KEY; then
	fill KEY_ENCRYPTION_KEY "$(openssl rand -base64 32)"
fi
if is_empty SESSION_SECRET; then
	fill SESSION_SECRET "$(openssl rand -hex 32)"
fi
if is_empty POCKET_ID_ENCRYPTION_KEY; then
	fill POCKET_ID_ENCRYPTION_KEY "$(openssl rand -base64 32)"
fi

pg_kept=false
if [ "$creating" = true ]; then
	pg_existing=false
	if [ -d "$pg_data" ]; then
		# Postgres owns its data directory with mode 700, so a directory we
		# cannot list holds a database too.
		if ! listing=$(ls -A "$pg_data" 2>/dev/null) || [ -n "$listing" ]; then
			pg_existing=true
		fi
	fi
	if [ "$pg_existing" = true ]; then
		pg_kept=true
	else
		password=$(openssl rand -hex 16)
		sed_args="$sed_args -e s|^POSTGRES_PASSWORD=.*\$|POSTGRES_PASSWORD=$password|"
		sed_args="$sed_args -e s|^\\(DATABASE_URL=[^:]*://[^:@/]*:\\)[^@]*@|\\1$password@|"
		filled="$filled POSTGRES_PASSWORD DATABASE_URL"
	fi
fi

mode_note=
current_mode=$(value_of AUTH_MODE)
if [ -n "$mode" ]; then
	if [ -z "$current_mode" ]; then
		if has_line AUTH_MODE; then
			sed_args="$sed_args -e s|^AUTH_MODE=[[:space:]]*\$|AUTH_MODE=$mode|"
		else
			appends="$appends AUTH_MODE=$mode"
		fi
		filled="$filled AUTH_MODE"
		current_mode=$mode
	elif [ "$current_mode" != "$mode" ]; then
		mode_note="AUTH_MODE is already $current_mode in .env, so it was left as it is (not $mode)."
	fi
fi

# sed_args holds only names, base64, and hex: no spaces, so word splitting
# (with set -f) is safe here and keeps the script POSIX.
if [ -n "$sed_args" ]; then
	# shellcheck disable=SC2086
	sed $sed_args "$source_file" >"$tmp"
else
	cat "$source_file" >"$tmp"
fi
for line in $appends; do
	printf '%s\n' "$line" >>"$tmp"
done

if [ -n "${password:-}" ]; then
	grep -q "^POSTGRES_PASSWORD=$password\$" "$tmp" ||
		fail "could not set POSTGRES_PASSWORD; .env was not written"
	grep -q "^DATABASE_URL=.*:$password@" "$tmp" ||
		fail "could not set the password in DATABASE_URL; .env was not written"
fi

if [ "$creating" = true ] || ! cmp -s "$tmp" "$env_file"; then
	mv "$tmp" "$env_file"
	tmp=
fi
chmod 600 "$env_file"

# --- Report: names only, never values ---------------------------------------

if [ "$creating" = true ]; then
	echo "Created .env from .env.example (readable only by you)."
fi
if [ -n "$filled" ]; then
	echo "Set in .env:$filled"
else
	echo "Nothing to set: every bootstrap secret in .env already has a value."
fi
if [ -n "$mode_note" ]; then
	echo "$mode_note"
fi

if [ "$pg_kept" = true ]; then
	cat <<'EOF'

Warning: .data/postgres already holds a database, which uses the password
focus_funnel. POSTGRES_PASSWORD and DATABASE_URL keep that password, because
a new one would lock the backend out. To change it, change it inside Postgres
first:
  docker compose exec postgres psql -U focus_funnel -d focus_funnel -c "ALTER USER focus_funnel PASSWORD '<new password>'"
then put the new password in POSTGRES_PASSWORD and in DATABASE_URL in .env.
EOF
fi

cat <<'EOF'

Keep a copy of KEY_ENCRYPTION_KEY somewhere safe, apart from this machine.
Saved provider keys cannot be read without it, and a new one cannot recover
them.
EOF

mcp=$(sed -n 's/^MCP_ENABLED=//p' "$env_file" | tail -n 1 | tr -d ' \t' | tr 'A-Z' 'a-z')
case $mcp in
true | 1 | yes | on)
	cat <<'EOF'

MCP_ENABLED=true: connector tokens go in .env under the names connectors.yaml
gives in each connector's auth.env. This script does not generate them; they
come from each connected service.
EOF
	;;
esac

# The settings the mode still needs, from .env as it is now.
missing=
case $current_mode in
oidc) needed="OIDC_ISSUER OIDC_CLIENT_ID OIDC_CLIENT_SECRET" ;;
firebase) needed="FIREBASE_PROJECT_ID FIREBASE_API_KEY FIREBASE_AUTH_DOMAIN" ;;
*) needed= ;;
esac
for name in $needed; do
	if [ -z "$(sed -n "s/^$name=//p" "$env_file" | tail -n 1 | tr -d ' \t')" ]; then
		missing="$missing $name"
	fi
done

echo
case $current_mode in
'')
	echo "AUTH_MODE is not set. Choose oidc, firebase, or demo (docs/login.md),"
	echo "then run this script again with --auth-mode, or set it in .env."
	;;
oidc | firebase)
	if [ -n "$missing" ]; then
		echo "Still to fill in .env for AUTH_MODE=$current_mode:$missing"
	fi
	;;
esac

echo
echo "Next steps (docs/setup.md):"
case $current_mode in
oidc)
	cat <<'EOF'
  1. With Pocket ID, start it first and register the app as a client
     (docs/login.md, Pocket ID):
       docker compose -f docker-compose.yml -f docker-compose.pocket-id.yml up -d pocket-id
     Then fill OIDC_ISSUER, OIDC_CLIENT_ID, and OIDC_CLIENT_SECRET in .env.
  2. Start everything, with the same -f files:
       docker compose -f docker-compose.yml -f docker-compose.pocket-id.yml up -d --build
  3. Find the setup token:
       docker compose -f docker-compose.yml -f docker-compose.pocket-id.yml logs backend | grep 'Setup token'
  4. Open the app's /setup (http://localhost:3000/setup by default, not
     Pocket ID's), log in, and enter the token.
EOF
	;;
demo)
	cat <<'EOF'
  1. Start the demo: docker compose -f docker-compose.yml -f docker-compose.demo.yml up --build
     Demo mode has no setup wizard.
EOF
	;;
*)
	cat <<'EOF'
  1. Start everything: docker compose up -d --build
  2. Find the setup token: docker compose logs backend | grep 'Setup token'
  3. Open the app's /setup (http://localhost:3000/setup by default), log in,
     and enter the token.
EOF
	;;
esac
