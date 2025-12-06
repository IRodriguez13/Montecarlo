#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <unistd.h>

#include "heads/cache.h"
#include "heads/dev.h"
#include "heads/montecarlo.h"

/*
    Helpers internos:
    -----------------
    - leer vendor/product desde sysfs
    - listar drivers candidatos
    - cargar driver con modprobe
    - buscar en dmesg si hubo actividad
*/

// ---------------------------------------------------------------
// LEE ATRIBUTO SYSFS
// ---------------------------------------------------------------
int read_sysattr(const char *path, char *buf, size_t buflen)
{
    FILE *f = fopen(path, "r");
    if (!f)
        return 0;

    if (!fgets(buf, buflen, f))
    {
        fclose(f);
        return 0;
    }

    // limpiar \n
    buf[strcspn(buf, "\n")] = 0;

    fclose(f);
    return 1;
}

// ---------------------------------------------------------------
// OBTENER vendor/product
// ---------------------------------------------------------------
void get_ids(const char *syspath, char *vendor, char *product)
{
    char path_v[1024], path_p[1024];

    snprintf(path_v, sizeof(path_v), "%s/idVendor", syspath);
    snprintf(path_p, sizeof(path_p), "%s/idProduct", syspath);

    if (!read_sysattr(path_v, vendor, 32))
        strcpy(vendor, "0000");

    if (!read_sysattr(path_p, product, 32))
        strcpy(product, "0000");
}

// ---------------------------------------------------------------
// LISTAR DRIVERS CANDIDATOS
//
// Devuelve la cantidad. Llena "out" con los nombres.
// Busca en:
//
//   /sys/bus/usb/drivers
//   /sys/bus/usb-serial/drivers
//   /sys/bus/hid/drivers
//
// ---------------------------------------------------------------
int list_candidate_drivers(char out[][128], int max)
{
    const char *paths[] = {
        "/sys/bus/usb/drivers",
        "/sys/bus/usb-serial/drivers",
        "/sys/bus/hid/drivers"};

    int count = 0;

    for (int i = 0; i < 3; i++)
    {
        DIR *d = opendir(paths[i]);
        if (!d)
            continue;

        struct dirent *ent;
        while ((ent = readdir(d)))
        {
            if (ent->d_name[0] == '.')
                continue;

            // algunos directorios no son drivers, filtrar por nombre real
            if (strcmp(ent->d_name, "module") == 0)
                continue;

            if (count < max)
            {
                snprintf(out[count], 128, "%s", ent->d_name);
                out[count][127] = '\0';
                count++;
            }
        }

        closedir(d);
    }

    return count;
}

// ---------------------------------------------------------------
// CARGAR DRIVER (modprobe)
// ---------------------------------------------------------------
int try_load_driver(const char *driver)
{
    char shortname[64];
    snprintf(shortname, sizeof(shortname), "%s", driver);

    strncpy(shortname, driver, sizeof(shortname) - 1);

    shortname[sizeof(shortname) - 1] = '\0';

    char cmd[256];
    snprintf(cmd, sizeof(cmd),
             "modprobe %s 2>/dev/null", shortname);

    int r = system(cmd);
    return (r == 0);
}

// ---------------------------------------------------------------
// DESCARGAR DRIVER
// ---------------------------------------------------------------
void unload_driver(const char *driver)
{
    char cmd[256];
    snprintf(cmd, sizeof(cmd),
             "modprobe -r %s 2>/dev/null", driver);
    system(cmd);
}

// ---------------------------------------------------------------
// CHEQUEAR DMESG POR ACTIVIDAD DEL DRIVER
// ---------------------------------------------------------------
int dmesg_has_activity(const char *driver)
{
    FILE *p = popen("dmesg | tail -n 30", "r");
    if (!p)
        return 0;

    char line[512];
    int found = 0;

    while (fgets(line, sizeof(line), p))
    {
        if (strstr(line, driver))
        {
            found = 1;
            break;
        }
    }

    pclose(p);
    return found;
}

// ---------------------------------------------------------------
// ALGORITMO PRINCIPAL MONTECARLO (CLI)
// ---------------------------------------------------------------
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
        int total = list_candidate_drivers(drivers, 256);
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
        return try_load_driver(argv[2]) ? 0 : 1;
    }
    else if (strcmp(argv[1], "unload") == 0)
    {
        if (argc < 3) return 1;
        unload_driver(argv[2]);
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
    get_ids(syspath, vendor, product);

    printf("[mc] vendor=%s product=%s\n", vendor, product);

    // ---------------------------------------------------------
    // LISTADO DE DRIVERS CANDIDATOS
    // ---------------------------------------------------------
    char drivers[256][128];
    int total = list_candidate_drivers(drivers, 256);

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

        if (!try_load_driver(drv))
        {
            printf("[mc] modprobe falló, paso al siguiente\n");
            continue;
        }

        sleep(1); // darle tiempo al kernel

        // 1) comprobación rápida
        if (dev_has_driver(dev))
        {
            printf("[mc] driver correcto encontrado: %s\n", drv);
            cache_save(vendor, product, drv);
            udev_device_unref(dev);
            udev_unref(udev);
            return;
        }

        // 2) comprobación profunda con dmesg
        if (dmesg_has_activity(drv))
        {
            printf("[mc] actividad en kernel para driver %s\n", drv);
            cache_save(vendor, product, drv);
            udev_device_unref(dev);
            udev_unref(udev);
            return;
        }

        // Si no funcionó → descargarlo
        unload_driver(drv);
    }

    // ---------------------------------------------------------
    // SI LLEGAMOS ACÁ, NINGÚN DRIVER FUNCIONÓ
    // ---------------------------------------------------------
    printf("[mc] ninguno de los drivers funcionó.\n");

    udev_device_unref(dev);
    udev_unref(udev);
}
