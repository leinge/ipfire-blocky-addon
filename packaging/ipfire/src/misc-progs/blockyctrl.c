/* Privileged, allowlisted controller for the IPFire Blocky add-on. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "setuid.h"

static const char *usage =
	"Usage: blockyctrl (apply|validate|start|stop|restart|enable|disable|status|public-data|private-data)\n";

static int run_manager(char *action) {
	char *args[] = { action, NULL };

	return run("/usr/lib/blocky/blocky-manager", args);
}

int main(int argc, char *argv[]) {
	if (!initsetuid())
		return 1;

	if (argc != 2) {
		fputs(usage, stderr);
		return 2;
	}

	if (strcmp(argv[1], "apply") == 0)
		return run_manager("apply");
	if (strcmp(argv[1], "validate") == 0)
		return run_manager("validate");
	if (strcmp(argv[1], "start") == 0)
		return run_manager("start");
	if (strcmp(argv[1], "stop") == 0)
		return run_manager("stop");
	if (strcmp(argv[1], "restart") == 0)
		return run_manager("restart");
	if (strcmp(argv[1], "enable") == 0)
		return run_manager("enable");
	if (strcmp(argv[1], "disable") == 0)
		return run_manager("disable");
	if (strcmp(argv[1], "status") == 0)
		return run_manager("status");
	if (strcmp(argv[1], "public-data") == 0)
		return run_manager("public-data");
	if (strcmp(argv[1], "private-data") == 0)
		return run_manager("private-data");

	fputs(usage, stderr);
	return 2;
}
