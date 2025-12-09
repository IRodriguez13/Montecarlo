/*
 * montecarlo-helper.c
 * Privileged helper for Montecarlo - executed via pkexec
 * 
 * This binary performs privileged operations (load/unload kernel modules)
 * with proper input sanitization to prevent command injection.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define MAX_MODULE_NAME 64

/*
 * Sanitize module name to prevent command injection
 * Only allows: alphanumeric characters, underscore, and dash
 */
int is_valid_module_name(const char *name) 
{
    if (!name || strlen(name) == 0 || strlen(name) >= MAX_MODULE_NAME) 
    {
        return 0;
    }
    
    for (int i = 0; name[i]; i++) 
    {
        if (!isalnum(name[i]) && name[i] != '_' && name[i] != '-') 
        {
            return 0;
        }
    }
    
    return 1;
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s [load|unload] <module_name>\n", argv[0]);
        fprintf(stderr, "This program is typically invoked by pkexec from the Montecarlo UI.\n");
        return 1;
    }
    
    const char *action = argv[1];
    const char *module = argv[2];
    
    // Validate action
    if (strcmp(action, "load") != 0 && strcmp(action, "unload") != 0) {
        fprintf(stderr, "Error: Invalid action '%s'. Use 'load' or 'unload'.\n", action);
        return 1;
    }
    
    // Sanitize module name (critical for security)
    if (!is_valid_module_name(module)) {
        fprintf(stderr, "Error: Invalid module name '%s'.\n", module);
        fprintf(stderr, "Module names must be alphanumeric with optional underscores/dashes.\n");
        return 1;
    }
    
    // Build command
    char cmd[256];
    if (strcmp(action, "load") == 0) {
        snprintf(cmd, sizeof(cmd), "modprobe %s 2>&1", module);
    } else { // unload
        snprintf(cmd, sizeof(cmd), "modprobe -r %s 2>&1", module);
    }
    
    // Execute
    int ret = system(cmd);
    
    if (ret == 0) {
        fprintf(stdout, "SUCCESS: Module %s %sed\n", module, action);
        return 0;
    } else {
        fprintf(stderr, "FAILED: Could not %s module %s\n", action, module);
        return 1;
    }
}
