#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <libudev.h>

#include "heads/dev.h"
#include "heads/cache.h"
// #include "heads/montecarlo.h"

// ----------------------------------------------------------
//  SPAWN WORKER
// ----------------------------------------------------------
static int run_worker_and_parse_json(const char *syspath)
{
    char cmd[1024];
    snprintf(cmd, sizeof(cmd), "./worker \"%s\"", syspath);

    FILE *p = popen(cmd, "r");
    if (!p)
    {
        fprintf(stderr, "[daemon] error ejecutando worker\n");
        return -1;
    }

    char jsonbuf[4096] = {0};
    size_t n = fread(jsonbuf, 1, sizeof(jsonbuf) - 1, p);
    jsonbuf[n] = '\0';
    pclose(p);

    printf("[daemon] worker returned JSON:\n%s\n", jsonbuf);

    // // Guardar en el cache
    // cache_save(jsonbuf);

    // EXTRAER DRIVER
    // ----------------------------------------------------------------
    //  simple parser: buscamos "\"driver\":\"XXXX\""
    //  después lo hacés en serio con jansson / cJSON
    // ----------------------------------------------------------------
    const char *pdrv = strstr(jsonbuf, "\"driver\"");
    if (!pdrv)
        return 0;

    const char *colon = strchr(pdrv, ':');
    if (!colon)
        return 0;

    const char *quote1 = strchr(colon, '"');
    if (!quote1)
        return 0;

    const char *quote2 = strchr(quote1 + 1, '"');
    if (!quote2)
        return 0;

    char driver[128] = {0};
    size_t len = quote2 - (quote1 + 1);
    if (len >= sizeof(driver))
        len = sizeof(driver) - 1;

    memcpy(driver, quote1 + 1, len);
    driver[len] = '\0';

    printf("[daemon] worker → driver detectado: %s\n", driver);

    // retornamos el driver en forma de hash simple
    // - 0 significa "none"
    // - 1 significa "hay driver"
    return (strcmp(driver, "none") == 0) ? 0 : 1;
}

// ----------------------------------------------------------
//  MAIN LOOP
// ----------------------------------------------------------
int main()
{
    printf("[daemon] iniciado\n");

    struct udev *udev = udev_new();
    if (!udev)
    {
        fprintf(stderr, "[daemon] error creando udev\n");
        return 1;
    }

    struct udev_monitor *mon =
        udev_monitor_new_from_netlink(udev, "udev");

    if (!mon)
    {
        fprintf(stderr, "[daemon] error creando monitor udev\n");
        udev_unref(udev);
        return 1;
    }

    udev_monitor_filter_add_match_subsystem_devtype(mon, "usb", NULL);
    udev_monitor_enable_receiving(mon);

    printf("[daemon] escuchando eventos USB...\n");

    while (1)
    {
        struct udev_device *dev = udev_monitor_receive_device(mon);
        if (!dev)
            continue;

        const char *action = udev_device_get_action(dev);
        const char *syspath = udev_device_get_syspath(dev);

        printf("[daemon] evento: %s → %s\n", action, syspath);

        // Sólo nos interesa cuando *agregan* un dispositivo USB
        if (strcmp(action, "add") == 0)
        {
            printf("[daemon] dispositivo agregado\n");

            if (dev_has_driver(dev))
            {
                printf("[daemon] driver ya presente, no hago nada.\n");
            }
            else
            {
                printf("[daemon] no hay driver: ejecutando worker\n");

                int has_driver = run_worker_and_parse_json(syspath);

                if (!has_driver)
                {
                    printf("[daemon] worker no encontró driver -> Iniciando UI...\n");
                    
                    pid_t pid = fork();
                    if (pid == 0)
                    {
                        // Child process
                        // Asumimos que ui.py está en el mismo directorio
                        // Seteamos DISPLAY si es necesario (asumimos :0 para demo)
                        setenv("DISPLAY", ":0", 0);
                        
                        // Necesitamos el user real para ejecutar la UI en el display del user
                        // (esto es un hack simplificado, en prod usaríamos dbus/polkit)
                        
                        // Ejecutamos la UI pasando el syspath
                        execlp("python3", "python3", "ui.py", syspath, NULL);
                        
                        // Si falla
                        perror("[daemon] execlp failed");
                        exit(1);
                    }
                    else if (pid > 0)
                    {
                        printf("[daemon] UI lanzada con PID %d\n", pid);
                    }
                    else
                    {
                        perror("[daemon] fork failed");
                    }
                }
                else
                {
                    printf("[daemon] worker encontró driver -> OK\n");
                }
            }
        }

        udev_device_unref(dev);
    }

    udev_unref(udev);
    return 0;
}
