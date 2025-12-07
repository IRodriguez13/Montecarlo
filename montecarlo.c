#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <unistd.h>
#include <libudev.h>

#include "heads/libmontecarlo.h"
#include "heads/cache.h"
#include "heads/montecarlo.h"

int main(int argc, char *argv[])
{
    if (argc < 2)
    {
        fprintf(stderr, "Uso: %s [list|run <syspath>|load <driver>|unload <driver>]\n", argv[0]);
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
        if (argc < 3) return 1;
        return mc_try_load_driver(argv[2]) ? 0 : 1;
    }
    else if (strcmp(argv[1], "unload") == 0)
    {
        if (argc < 3) return 1;
        mc_unload_driver(argv[2]);
        return 0;
    }
    else if (strcmp(argv[1], "run") == 0)
    {
        if (argc < 3)
        {
            fprintf(stderr, "Uso: %s run <syspath>\n", argv[0]);
            return 1;
        }
        mc_run(argv[2]);
        return 0;
    }

    return 1;
}

void mc_run(const char *syspath)
{
    printf("[mc] iniciando montecarlo para %s\n", syspath);

    char vendor[32], product[32];
    mc_get_ids(syspath, vendor, product);

    printf("[mc] vendor=%s product=%s\n", vendor, product);

    // ---------------------------------------------------------
    // LISTADO DE DRIVERS CANDIDATOS
    // ---------------------------------------------------------
    char drivers[256][128];
    int total = mc_list_candidate_drivers(drivers, 256);

    printf("[mc] candidatos encontrados: %d\n", total);

    if (total == 0)
    {
        printf("[mc] no hay candidatos. Abortando.\n");
        return;
    }

    // ---------------------------------------------------------
    // LOOP MONTECARLO
    // ---------------------------------------------------------
    struct udev *udev = udev_new();
    if (!udev)
    {
        printf("[mc] error creando udev\n");
        return;
    }

    struct udev_device *dev =
        udev_device_new_from_syspath(udev, syspath);

    if (!dev)
    {
        printf("[mc] error obteniendo udev_device\n");
        udev_unref(udev);
        return;
    }

    for (int i = 0; i < total; i++)
    {
        const char *drv = drivers[i];

        printf("[mc] probando driver: %s\n", drv);

        if (!mc_try_load_driver(drv))
        {
            printf("[mc] modprobe falló, paso al siguiente\n");
            continue;
        }

        sleep(1); // darle tiempo al kernel

        // 1) comprobación rápida
        if (mc_dev_has_driver(syspath))
        {
            printf("[mc] driver correcto encontrado: %s\n", drv);
            cache_save(vendor, product, drv);
            udev_device_unref(dev);
            udev_unref(udev);
            return;
        }

        // 2) comprobación profunda con dmesg
        if (mc_dmesg_has_activity(drv))
        {
            printf("[mc] actividad en kernel para driver %s\n", drv);
            cache_save(vendor, product, drv);
            udev_device_unref(dev);
            udev_unref(udev);
            return;
        }

        // Si no funcionó → descargarlo
        mc_unload_driver(drv);
    }

    // ---------------------------------------------------------
    // SI LLEGAMOS ACÁ, NINGÚN DRIVER FUNCIONÓ
    // ---------------------------------------------------------
    printf("[mc] ninguno de los drivers funcionó. Segúramente convenga un kpanic!\n");

    udev_device_unref(dev);
    udev_unref(udev);
}
