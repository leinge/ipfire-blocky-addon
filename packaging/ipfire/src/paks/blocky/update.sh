#!/bin/bash
###############################################################################
# Pakfire update lifecycle for Blocky.                                        #
###############################################################################

set -e
. /opt/pakfire/lib/functions.sh

update_dir="/var/tmp/blocky-update.$$"
install -d -m 0700 "$update_dir"
trap 'rm -rf "$update_dir"' EXIT

was_running=false
was_enabled=false
pidof blocky >/dev/null 2>&1 && was_running=true
[ -e /etc/rc.d/rc3.d/S50blocky ] || [ -L /etc/rc.d/rc3.d/S50blocky ] && was_enabled=true

extract_backup_includes
make_backup "${NAME}"

for path in /usr/bin/blocky /etc/blocky/config.yml /var/lib/blocky/enforcement.json; do
	if [ -e "$path" ]; then
		cp -a "$path" "$update_dir/$(basename "$path")"
	fi
done

# Kernel enforcement remains installed while package files are replaced.
extract_files
restore_backup "${NAME}"

if [ -e "$update_dir/enforcement.json" ]; then
	cp -a "$update_dir/enforcement.json" /var/lib/blocky/enforcement.json
fi

install -d -m 0750 -o root -g nobody /var/ipfire/blocky
install -d -m 0700 -o nobody -g nobody /var/ipfire/blocky/pending
install -d -m 0750 -o blocky -g blocky /var/cache/blocky/lists /var/log/blocky /run/blocky
install -d -m 0750 -o root -g blocky /var/lib/blocky
chown root:blocky /etc/blocky/config.yml
chmod 0640 /etc/blocky/config.yml
chown root:nobody /var/ipfire/blocky/config.json /var/ipfire/blocky/settings.json /var/ipfire/blocky/status.json
chmod 0640 /var/ipfire/blocky/config.json /var/ipfire/blocky/settings.json /var/ipfire/blocky/status.json

/usr/lib/blocky/blocky-manager hook install
rebuild_langcache

rm -f /etc/rc.d/rc3.d/S50blocky /etc/rc.d/rc3.d/off/S50blocky
if [ "$was_enabled" = true ]; then
	ln -sfn ../init.d/blocky /etc/rc.d/rc3.d/S50blocky
else
	mkdir -p /etc/rc.d/rc3.d/off
	ln -sfn ../../init.d/blocky /etc/rc.d/rc3.d/off/S50blocky
fi

if ! /usr/lib/blocky/blocky-manager validate; then
	[ -e "$update_dir/blocky" ] && cp -a "$update_dir/blocky" /usr/bin/blocky
	[ -e "$update_dir/config.yml" ] && cp -a "$update_dir/config.yml" /etc/blocky/config.yml
	[ -e "$update_dir/enforcement.json" ] && cp -a "$update_dir/enforcement.json" /var/lib/blocky/enforcement.json
	$was_running && /etc/rc.d/init.d/blocky restart || true
	echo "Blocky update validation failed; restored the previous binary and runtime state." >&2
	exit 1
fi

if [ "$was_running" = true ]; then
	if ! /etc/rc.d/init.d/blocky restart || ! /usr/bin/blocky healthcheck --bindip 127.0.0.1 --port 1053; then
		[ -e "$update_dir/blocky" ] && cp -a "$update_dir/blocky" /usr/bin/blocky
		[ -e "$update_dir/config.yml" ] && cp -a "$update_dir/config.yml" /etc/blocky/config.yml
		[ -e "$update_dir/enforcement.json" ] && cp -a "$update_dir/enforcement.json" /var/lib/blocky/enforcement.json
		/etc/rc.d/init.d/blocky restart || true
		echo "Blocky update failed health verification; restored the previous runtime." >&2
		exit 1
	fi
fi

/usr/lib/blocky/blocky-firewall reload
exit 0
