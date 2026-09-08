#!/bin/bash
###############################################################################
# Pakfire install lifecycle for Blocky.                                       #
###############################################################################

set -e
. /opt/pakfire/lib/functions.sh

if ! getent group blocky >/dev/null; then
	groupadd -r blocky
fi
if ! getent passwd blocky >/dev/null; then
	useradd -r -g blocky -c "Blocky DNS proxy" -d /var/empty -s /bin/false blocky
fi

extract_files
restore_backup "${NAME}"

install -d -m 0750 -o root -g nobody /var/ipfire/blocky
install -d -m 0700 -o nobody -g nobody /var/ipfire/blocky/pending
install -d -m 0750 -o blocky -g blocky /var/cache/blocky/lists /var/log/blocky /run/blocky
install -d -m 0750 -o root -g blocky /var/lib/blocky
chown root:blocky /etc/blocky/config.yml
chmod 0640 /etc/blocky/config.yml
chown root:nobody /var/ipfire/blocky/config.json /var/ipfire/blocky/settings.json /var/ipfire/blocky/status.json
chmod 0640 /var/ipfire/blocky/config.json /var/ipfire/blocky/settings.json /var/ipfire/blocky/status.json
chown root:blocky /var/lib/blocky/enforcement.json
chmod 0600 /var/lib/blocky/enforcement.json

/usr/lib/blocky/blocky-manager initialize
/usr/lib/blocky/blocky-manager hook install
rebuild_langcache

mkdir -p /etc/rc.d/rc3.d/off
if [ ! -e /etc/rc.d/rc3.d/S50blocky ] && [ ! -L /etc/rc.d/rc3.d/S50blocky ]; then
	ln -sfn ../../init.d/blocky /etc/rc.d/rc3.d/off/S50blocky
fi
ln -sfn ../init.d/blocky /etc/rc.d/rc0.d/K50blocky
ln -sfn ../init.d/blocky /etc/rc.d/rc6.d/K50blocky

# A fresh install remains stopped and disabled. A restored enforced backup was
# necessarily boot-enabled by the UI, so validate/start it before restoring
# firewall policy.
if /usr/lib/blocky/blocky-manager enforcement-enabled; then
	/usr/lib/blocky/blocky-manager enable
	/usr/lib/blocky/blocky-manager start
	/usr/lib/blocky/blocky-firewall start
fi

exit 0
