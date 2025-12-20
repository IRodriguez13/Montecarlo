/*
 * montecarlo-helper.c
 * Privileged helper for Montecarlo - executed via pkexec
 *
 * This binary performs privileged operations (load/unload kernel modules)
 * with proper input sanitization to prevent command injection.
 */

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define MAX_MODULE_NAME 64


bool is_valid_char_name(const char c)
{
    return isalnum((unsigned char)c) || c == '_' || c == '-';
}

bool is_valid_module_name(const char *name)
{
    if (!name)
        return false;
    
    size_t len = strlen(name);

    if (len == 0 || len >= MAX_MODULE_NAME)
        return false;
    
    if (isdigit((unsigned char)name[0]) || name[0] == '-')
        return false;
    
    for (size_t i = 0; i < len; i++)
    {
        if (!is_valid_char_name(name[i]))
            return false;
    }
    
    return true;
}

int main(int argc, char *argv[])
{
#include "systemd/libsystemd.h"

// ... (existing includes)

    if (argc != 4 && argc != 3)
    {
        fprintf(stderr, "Usage: %s [load|unload|service] [args...]\n", argv[0]);
        fprintf(stderr, "  load/unload <module>\n");
        fprintf(stderr, "  service <action> <service_name>\n");
        return 1;
    }

    const char *mode = argv[1];

    // --- MODULE OPERATIONS ---
    if (strcmp(mode, "load") == 0 || strcmp(mode, "unload") == 0)
    {
        if (argc != 3) {
            fprintf(stderr, "Usage: %s %s <module>\n", argv[0], mode);
            return 1;
        }
        const char *module = argv[2];

        if (!is_valid_module_name(module))
        {
            fprintf(stderr, "Error: Invalid module name '%s'.\n", module);
            return 1;
        }

        char cmd[256];
        if (strcmp(mode, "load") == 0)
            snprintf(cmd, sizeof(cmd), "modprobe %s 2>&1", module);
        else
            snprintf(cmd, sizeof(cmd), "modprobe -r %s 2>&1", module);

        int ret = system(cmd);
        if (ret != 0) {
            fprintf(stderr, "FAILED: %s module %s\n", mode, module);
            return 1;
        }
        fprintf(stdout, "SUCCESS: Module %s %sed\n", module, mode);
        return 0;
    }

    // --- SERVICE OPERATIONS ---
    if (strcmp(mode, "service") == 0)
    {
        if (argc != 4) {
            fprintf(stderr, "Usage: %s service <start|stop|enable|disable> <name>\n", argv[0]);
            return 1;
        }
        const char *action = argv[2];
        const char *service = argv[3];

        // Sanitize service name (basic check)
        if (strchr(service, '/') || strchr(service, ';') || strchr(service, '|')) {
            fprintf(stderr, "Invalid service name.\n");
            return 1;
        }

        int r = -1;
        if (strcmp(action, "start") == 0)
            r = systemd_start_service(service);
        else if (strcmp(action, "stop") == 0)
            r = systemd_stop_service(service);
        else if (strcmp(action, "enable") == 0)
            r = systemd_enable_service(service);
        else if (strcmp(action, "disable") == 0)
            r = systemd_disable_service(service);
        else {
            fprintf(stderr, "Unknown service action: %s\n", action);
            return 1;
        }

        if (r < 0) {
            fprintf(stderr, "FAILED: %s %s (Error code: %d)\n", action, service, r);
            return 1;
        }
        
        fprintf(stdout, "SUCCESS: Service %s %sd\n", service, action);
        return 0;
    }

    fprintf(stderr, "Unknown mode: %s\n", mode);
    return 1;
}
