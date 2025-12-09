#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "heads/libmontecarlo.h"

int main(int argc, char *argv[])
{
    if (argc < 2)
    {
        fprintf(stderr, "Uso: %s [list|load <driver>|unload <driver>]\n", argv[0]);
        return 1;
    }

    if (strcmp(argv[1], "list") == 0)
    {
        char drivers[256][128];
        int total = mc_list_candidate_drivers(drivers, 256);
        printf("[\n");
        for (int i = 0; i < total; i++)
        {
            printf("  \"%s\"%s\n", drivers[i], (i < total - 1) ? "," : "");
        }
        printf("]\n");
        return 0;
    }
    else if (strcmp(argv[1], "load") == 0)
    {
        if (argc < 3)
        {
            fprintf(stderr, "Uso: %s load <driver>\n", argv[0]);
            return 1;
        }
        return mc_try_load_driver(argv[2]) ? 0 : 1;
    }
    else if (strcmp(argv[1], "unload") == 0)
    {
        if (argc < 3)
        {
            fprintf(stderr, "Uso: %s unload <driver>\n", argv[0]);
            return 1;
        }
        mc_unload_driver(argv[2]);
        return 0;
    }

    fprintf(stderr, "Comando desconocido: %s\n", argv[1]);
    fprintf(stderr, "Uso: %s [list|load <driver>|unload <driver>]\n", argv[0]);
    return 1;
}
