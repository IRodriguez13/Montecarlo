#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <dirent.h>
#include <unistd.h>
#include <libudev.h>

#include "heads/libmontecarlo.h"

/* READ SYSFS ATTRIBUTE */
int mc_read_sysattr(const char *path, char *buf, size_t buflen)
{
    FILE *f = fopen(path, "r");
    if (!f)
    {
        return 0;
    }

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

/* GET ID_VENDOR / ID_PRODUCT */
void mc_get_ids(const char *syspath, char *vendor, char *product)
{
    char path_v[1024], path_p[1024];

    snprintf(path_v, sizeof(path_v), "%s/idVendor", syspath);
    snprintf(path_p, sizeof(path_p), "%s/idProduct", syspath);

    if (!mc_read_sysattr(path_v, vendor, 32))
    {
        strcpy(vendor, "0000");
    }

    if (!mc_read_sysattr(path_p, product, 32))
    {
        strcpy(product, "0000");
    }
}

/* LIST CANDIDATE DRIVERS */
/* Returns count. Fills "out" with names. */
/* Scans: */
/*   /sys/bus/usb/drivers */
/*   /sys/bus/usb-serial/drivers */
/*   /sys/bus/hid/drivers */
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
        {
            continue;
        }

        struct dirent *ent;
        while ((ent = readdir(d)))
        {
            if (ent->d_name[0] == '.')
            {
                continue;
            }

            /* Filter out non-driver directories (e.g., 'module') */
            if (strcmp(ent->d_name, "module") == 0)
            {
                continue;
            }

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

/* LOAD DRIVER (modprobe) */
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

/* UNLOAD DRIVER */
int mc_unload_driver(const char *driver)
{
    char cmd[256];
    snprintf(cmd, sizeof(cmd), "modprobe -r %s 2>/dev/null", driver);
    int r = system(cmd);
    return (WEXITSTATUS(r) == 0);
}

/* CHECK DMESG FOR ACTIVITY */
int mc_dmesg_has_activity(const char *driver)
{
    FILE *p = popen("dmesg | tail -n 30", "r");
    if (!p)
    {
        return 0;
    }

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

/* CHECK IF DEVICE HAS DRIVER BOUND */
int mc_dev_has_driver(const char *syspath)
{
    struct udev *udev = udev_new();
    if (!udev)
    {
        return 0;
    }
    
    struct udev_device *dev = udev_device_new_from_syspath(udev, syspath);
    if (!dev)
    {
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
    if (access(driver_link, F_OK) == 0)
    {
        has_driver = 1; 
    }
    
    udev_device_unref(dev);
    udev_unref(udev);
    return has_driver;
}

/* LIST ALL USB DEVICES */
int mc_list_all_usb_devices(mc_device_info_t *out, int max)
{
    struct udev *udev = udev_new();
    if (!udev)
    {
        return 0;
    }

    struct udev_enumerate *enumerate = udev_enumerate_new(udev);
    udev_enumerate_add_match_subsystem(enumerate, "usb");
    udev_enumerate_scan_devices(enumerate);

    struct udev_list_entry *devices, *dev_list_entry;
    devices = udev_enumerate_get_list_entry(enumerate);

    int count = 0;
    udev_list_entry_foreach(dev_list_entry, devices)
    {
        if (count >= max)
        {
            break;
        }

        const char *path = udev_list_entry_get_name(dev_list_entry);
        struct udev_device *dev = udev_device_new_from_syspath(udev, path);

        if (!dev)
        {
            continue;
        }

        // Verify it's an interface (where drivers bind)
        const char *devtype = udev_device_get_devtype(dev);
        if (!devtype || strcmp(devtype, "usb_interface") != 0)
        {
            udev_device_unref(dev);
            continue;
        }

        // FILTERING: Skip Hubs (Class 09)
        const char *class_str = udev_device_get_sysattr_value(dev, "bInterfaceClass");
        if (class_str && strcmp(class_str, "09") == 0)
        {
            udev_device_unref(dev);
            continue;
        }

        // Get Parent for Metadata
        // NOTE: udev_device_get_parent_* returns a POINTER to the parent device which is linked to the child.
        // It does NOT increment the refcount. The parent is valid as long as 'dev' is valid.
        // We do NOT need to unref 'parent' explicitly.
        struct udev_device *parent = udev_device_get_parent_with_subsystem_devtype(dev, "usb", "usb_device");
        if (!parent)
        {
            udev_device_unref(dev);
            continue; // Can't find parent info, skip
        }

        // Filter Root Hubs via Parent Class
        const char *p_class = udev_device_get_sysattr_value(parent, "bDeviceClass");
        if (p_class && strcmp(p_class, "09") == 0)
        {
             udev_device_unref(dev);
             continue;
        }

        // Fill struct using Parent Info
        strncpy(out[count].syspath, path, 255);
        
        const char *vendor = udev_device_get_sysattr_value(parent, "idVendor");
        const char *product = udev_device_get_sysattr_value(parent, "idProduct");
        const char *prod_name = udev_device_get_sysattr_value(parent, "product");
        const char *man_name = udev_device_get_sysattr_value(parent, "manufacturer");

        snprintf(out[count].vidpid, 31, "%s:%s", vendor ? vendor : "????", product ? product : "????");
        
        // Append Interface Number to Product Name to distinguish
        const char *iface_num = udev_device_get_sysattr_value(dev, "bInterfaceNumber");
        char combined_name[128];
        if (prod_name)
        {
            if (man_name)
            {
                 snprintf(combined_name, 127, "%s %s", man_name, prod_name);
            }
            else
            {
                 strncpy(combined_name, prod_name, 127);
            }
        }
        else
        {
             strncpy(combined_name, "Unknown Device", 127);
        }
        
        if (iface_num)
        {
            snprintf(out[count].product, 127, "%.110s (If: %s)", combined_name, iface_num);
        }
        else
        {
            strncpy(out[count].product, combined_name, 127);
        }

        // Check for driver link on the INTERFACE
        char driver_path[1024];
        snprintf(driver_path, sizeof(driver_path), "%s/driver", path);
        
        char driver_target[1024];
        int len = readlink(driver_path, driver_target, sizeof(driver_target)-1);
        if (len != -1)
        {
            driver_target[len] = '\0';
            const char *dname = strrchr(driver_target, '/');
            const char *final_driver = dname ? dname + 1 : "generic-usb";
            
            // FILTERING: Skip Host Controllers explicitly
            if (strstr(final_driver, "hcd") != NULL || strcmp(final_driver, "hub") == 0)
            {
                 udev_device_unref(dev);
                 continue;
            }
            
            strncpy(out[count].driver, final_driver, 63);
        }
        else
        {
             strcpy(out[count].driver, "None");
        }
        
        count++;
        // udev_device_unref(parent); // Incorrect: parent is borrowed from dev
        udev_device_unref(dev);
    }

    udev_enumerate_unref(enumerate);
    udev_unref(udev);

    return count;
}

/* CHECK IF MODULE HAS HOLDERS */
// Returns 1 if /sys/module/<name>/holders is NOT empty (module is a dependency).
// Returns 0 if empty (independent module).
int mc_module_has_holders(const char *module)
{
    char path[256];
    snprintf(path, sizeof(path), "/sys/module/%s/holders", module);
    
    DIR *dir = opendir(path);
    if (!dir)
    {
        return 0; // If holders dir doesn't exist, assume no holders (or built-in?)
    }
    
    struct dirent *ent;
    int has_holders = 0;
    
    while ((ent = readdir(dir)) != NULL)
    {
        if (ent->d_name[0] == '.') 
        {
            continue;
        }
        // Found a holder!
        has_holders = 1;
        break;
    }
    
    closedir(dir);
    return has_holders;
}

/* CHECK MODULE USE COUNT */
int mc_get_module_refcount(const char *module)
{
    // Check /sys/module/<name>/refcnt
    char path[256];
    snprintf(path, sizeof(path), "/sys/module/%s/refcnt", module);
    
    FILE *f = fopen(path, "r");
    if (!f) 
    {
        return -1; // Built-in or doesn't exist
    }
    
    int ref = 0;
    if (fscanf(f, "%d", &ref) != 1)
    {
        ref = -1;
    }
    fclose(f);
    return ref;
}

/* LIST LOADED MODULES */
// Writes null-separated module names to out_buf. Returns count.
int mc_list_loaded_modules(char *out_buf, int max_size)
{
    FILE *f = fopen("/proc/modules", "r");
    if (!f)
    {
        return 0;
    }
    
    int count = 0;
    int written = 0;
    char line[256];
    
    while (fgets(line, sizeof(line), f))
    {
        char name[64];
        if (sscanf(line, "%63s", name) == 1)
        {
            int len = strlen(name);
            if (written + len + 1 < max_size)
            {
                strcpy(out_buf + written, name);
                written += len + 1;
                count++;
            }
            else
            {
                break;
            }
        }
    }
    
    fclose(f);
    return count;
}

/* CHECK IF DRIVER IS IN USE (Bus Check) */
// Returns 1 if driver has devices bound in /sys/bus/.../drivers/<driver>/
// Returns 0 if safe (no devices).
int mc_driver_is_in_use(const char *driver)
{
    const char *buses[] = {"usb", "hid", NULL};
    char path[512];
    
    for (int i = 0; buses[i] != NULL; i++)
    {
        snprintf(path, sizeof(path), "/sys/bus/%s/drivers/%s", buses[i], driver);
        
        DIR *dir = opendir(path);
        if (!dir)
        {
            continue; // Bus or driver doesn't exist here
        }
        
        struct dirent *ent;
        int found = 0;
        
        while ((ent = readdir(dir)) != NULL)
        {
            if (ent->d_name[0] == '.')
            {
                continue;
            }
            // FIX: Ignore 'module' symlink which links back to the module owner
            if (strcmp(ent->d_name, "module") == 0)
            {
                continue;
            }
            
            char fullpath[1024];
            snprintf(fullpath, sizeof(fullpath), "%s/%s", path, ent->d_name);
            
            struct stat st;
            if (lstat(fullpath, &st) == 0 && S_ISLNK(st.st_mode)) 
            {
                found = 1;
                break; 
            }
        }
        
        closedir(dir);
        if (found)
        {
            return 1;
        }
    }
    
    return 0;
}
