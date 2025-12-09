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
                snprintf(out[count], 128, "%.127s", ent->d_name);
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

/* --------------------------------------------------------------- */
/* LIST ALL USB DEVICES                                            */
/* --------------------------------------------------------------- */
int mc_list_all_usb_devices(mc_device_info_t *out, int max)
{
    struct udev *udev = udev_new();
    if (!udev) return 0;

    struct udev_enumerate *enumerate = udev_enumerate_new(udev);
    udev_enumerate_add_match_subsystem(enumerate, "usb");
    udev_enumerate_scan_devices(enumerate);

    struct udev_list_entry *devices, *dev_list_entry;
    devices = udev_enumerate_get_list_entry(enumerate);

    int count = 0;
    udev_list_entry_foreach(dev_list_entry, devices) {
        if (count >= max) break;

        const char *path = udev_list_entry_get_name(dev_list_entry);
        struct udev_device *dev = udev_device_new_from_syspath(udev, path);

        if (!dev) continue;

        // Verify it's a physical device, not an interface (usually has devtype "usb_device")
        const char *devtype = udev_device_get_devtype(dev);
        if (!devtype || strcmp(devtype, "usb_device") != 0) {
            udev_device_unref(dev);
            continue;
        }

        // Fill struct
        strncpy(out[count].syspath, path, 255);
        
        const char *vendor = udev_device_get_sysattr_value(dev, "idVendor");
        const char *product = udev_device_get_sysattr_value(dev, "idProduct");
        const char *prod_name = udev_device_get_sysattr_value(dev, "product");
        const char *man_name = udev_device_get_sysattr_value(dev, "manufacturer");

        snprintf(out[count].vidpid, 31, "%s:%s", vendor ? vendor : "????", product ? product : "????");
        
        if (prod_name) {
            if (man_name)
                snprintf(out[count].product, 127, "%s %s", man_name, prod_name);
            else
                strncpy(out[count].product, prod_name, 127);
        } else {
             strncpy(out[count].product, "Unknown Device", 127);
        }

        // Check for driver (USB devices generally bind slightly differently, often interfaces bind)
        // For the purpose of this tool, we check if ANY interface has a driver or if the device itself is claimed.
        // But the previous checking logic was at interface level usually? 
        // Let's stick to the "driver" link check or basic parent logic.
        // Ideally we want to see if this device is "working".
        
        // Actually, usb_device usually doesn't have a specific driver, the interfaces do.
        // But generic drivers might attach. 
        // For dashboard list, let's just show "usb-generic" or similar if handled, 
        // or check the first interface's driver.
        
        // Let's see if we can find the driver of the first interface usually.
        // Or just leave it empty if the device itself isn't bound (which is normal for USB composition).
        
        // User wants to know if "drivers are loaded".
        // Let's try to find an active driver on the device or its interfaces.
        
        // Simple heuristic: "usb" is the driver for the device itself usually.
        // Let's check syspath/driver link used in other functions.
        char driver_path[1024];
        snprintf(driver_path, sizeof(driver_path), "%s/driver", path);
        
        char driver_target[1024];
        int len = readlink(driver_path, driver_target, sizeof(driver_target)-1);
        if (len != -1) {
            driver_target[len] = '\0';
            const char *dname = strrchr(driver_target, '/');
            strncpy(out[count].driver, dname ? dname + 1 : "generic-usb", 63);
        } else {
             strcpy(out[count].driver, "None");
        }
        
        count++;
        udev_device_unref(dev);
    }

    udev_enumerate_unref(enumerate);
    udev_unref(udev);

    return count;
}
