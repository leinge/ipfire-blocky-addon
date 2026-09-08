#!/bin/bash
###############################################################################
# Pakfire uninstall lifecycle for Blocky.                                     #
###############################################################################

set -e
. /opt/pakfire/lib/functions.sh

# Uninstall is explicit recovery intent: remove enforcement and verify Knot.
/usr/sbin/blocky-recovery
/etc/rc.d/init.d/blocky stop || true
/usr/lib/blocky/blocky-manager hook uninstall
make_backup "${NAME}"

rm -f /etc/rc.d/rc3.d/S50blocky /etc/rc.d/rc3.d/off/S50blocky
rm -rf /run/blocky /var/lib/blocky/last-known-good
remove_files
rebuild_langcache
exit 0
