.PHONY: check test stage-check blocky-check

check: test stage-check blocky-check

test:
	python3 -m unittest discover -s tests/unit -v
	node --check packaging/ipfire/html/html/include/blocky.js
	perl -c packaging/ipfire/html/cgi-bin/blocky.cgi
	sh -n packaging/ipfire/src/blocky/blocky-manager \
		packaging/ipfire/src/blocky/blocky-firewall \
		packaging/ipfire/src/blocky/blocky-recovery \
		packaging/ipfire/src/initscripts/packages/blocky
	bash -n packaging/ipfire/src/paks/blocky/*.sh
	gcc -fsyntax-only -Wall -Wextra \
		-I tests/fixtures/ipfire-misc-progs \
		packaging/ipfire/src/misc-progs/blockyctrl.c

stage-check:
	python3 -m json.tool packaging/ipfire/config/blocky/config.schema.json >/dev/null
	python3 -m json.tool packaging/ipfire/config/blocky/doh-providers.json >/dev/null
	@if [ -n "$(IPFIRE_TREE)" ]; then tools/stage-ipfire-overlay --check "$(IPFIRE_TREE)"; fi

blocky-check:
	@if [ -n "$(BLOCKY_BIN)" ]; then tools/validate-with-blocky "$(BLOCKY_BIN)"; fi
