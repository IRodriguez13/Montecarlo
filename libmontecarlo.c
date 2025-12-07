#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <unistd.h>
#include <libudev.h>

#include "heads/libmontecarlo.h"

/* --------------------------------------------------------------- */
/* READ SYSFS ATTRIBUTE                                            */
/* --------------------------------------------------------------- */
int mc_read_sysattr(const char *path, char *buf, size_t buflen)
{
    FILE *f = fopen(path, "r");
    if (!f)
        return 0;

    if (!fgets(buf, buflen, f))
    {
        fclose(f);
        return 0;
    }

    /* Clean trailing newline */
    buf[strcspn(buf, "\n")] = 0;

    fclose(f);
    return 1;
}

/* --------------------------------------------------------------- */
/* GET ID_VENDOR / ID_PRODUCT                                      */
/* --------------------------------------------------------------- */
void mc_get_ids(const char *syspath, char *vendor, char *product)
{
    char path_v[1024], path_p[1024];

    snprintf(path_v, sizeof(path_v), "%s/idVendor", syspath);
    snprintf(path_p, sizeof(path_p), "%s/idProduct", syspath);

    if (!mc_read_sysattr(path_v, vendor, 32))
        strcpy(vendor, "0000");

    if (!mc_read_sysattr(path_p, product, 32))
        strcpy(product, "0000");
}

/* --------------------------------------------------------------- */
/* LIST CANDIDATE DRIVERS                                          */
/*                                                                 */
/* Returns count. Fills "out" with names.                          */
/* Scans:                                                          */
/*   /sys/bus/usb/drivers                                          */
/*   /sys/bus/usb-serial/drivers                                   */
/*   /sys/bus/hid/drivers                                          */
/* --------------------------------------------------------------- */
int mc_list_candidate_drivers(char out[][128], int max)
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

            /* Filter out non-driver directories (e.g., 'module') */
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

/* --------------------------------------------------------------- */
/* LOAD DRIVER (modprobe)                                          */
/* --------------------------------------------------------------- */
int mc_try_load_driver(const char *driver)
{
    char shortname[64];
    snprintf(shortname, sizeof(shortname), "%s", driver);
    /* Sanitize if necessary */
    
    char cmd[256];
    /* Redirect stderr to null to avoid noise */
    snprintf(cmd, sizeof(cmd), "modprobe %s 2>/dev/null", shortname);

    int r = system(cmd);
    return (r == 0);
}

/* --------------------------------------------------------------- */
/* UNLOAD DRIVER                                                   */
/* --------------------------------------------------------------- */
void mc_unload_driver(const char *driver)
{
    char cmd[256];
    snprintf(cmd, sizeof(cmd), "modprobe -r %s 2>/dev/null", driver);
    system(cmd);
}

/* --------------------------------------------------------------- */
/* CHECK DMESG FOR ACTIVITY                                        */
/* --------------------------------------------------------------- */
int mc_dmesg_has_activity(const char *driver)
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

/* --------------------------------------------------------------- */
/* CHECK IF DEVICE HAS DRIVER BOUND                                */
/* --------------------------------------------------------------- */
int mc_dev_has_driver(const char *syspath)
{
    struct udev *udev = udev_new();
    if (!udev) return 0;
    
    struct udev_device *dev = udev_device_new_from_syspath(udev, syspath);
    if (!dev) {
        udev_unref(udev);
        return 0;
    }
    
    struct udev_device *driver = udev_device_get_parent_with_subsystem_devtype(dev, "usb", "usb_interface");
    /* 
     * If not found via parent, checks if "driver" link exists in syspath
     * Simplified logic for demonstration.
     */
    
    char driver_link[1024];
    snprintf(driver_link, sizeof(driver_link), "%s/driver", syspath);
    
    int has_driver = 0;
    if (access(driver_link, F_OK) == 0) {
        has_driver = 1; 
    }
    
    udev_device_unref(dev);
    udev_unref(udev);
    return has_driver;
}
