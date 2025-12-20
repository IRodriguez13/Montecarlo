#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <dirent.h>
#include <unistd.h>
#include <libudev.h>
#include <stdbool.h>

#include "heads/libmontecarlo.h"

/* READ SYSFS ATTRIBUTE */
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
/*   /sys/bus/pci/drivers */
/*   /sys/bus/i2c/drivers */
/*   /sys/bus/sdio/drivers */
/*   /sys/bus/scsi/drivers */
int mc_list_candidate_drivers(char out[][128], int max)
{
    const char *bus_paths[] = {
        "/sys/bus/usb/drivers",
        "/sys/bus/usb-serial/drivers",
        "/sys/bus/hid/drivers",
        "/sys/bus/pci/drivers",
        "/sys/bus/i2c/drivers",
        "/sys/bus/sdio/drivers",
        "/sys/bus/scsi/drivers",
        "/sys/bus/pcmcia/drivers",
        NULL};

    int count = 0;

    for (int b = 0; bus_paths[b] != NULL; b++)
    {
        DIR *dir = opendir(bus_paths[b]);
        if (!dir)
            continue;

        struct dirent *ent;
        while ((ent = readdir(dir)) != NULL)
        {
            if (ent->d_name[0] == '.')
                continue;

            // Check if it's a directory or symlink
            char full_path[512];
            snprintf(full_path, sizeof(full_path), "%s/%s", bus_paths[b], ent->d_name);

            struct stat st;
            if (lstat(full_path, &st) == 0 && S_ISDIR(st.st_mode))
            {
                strncpy(out[count], ent->d_name, 127);
                out[count][127] = '\0';
                count++;

                if (count >= max)
                {
                    closedir(dir);
                    return count;
                }
            }
        }
        closedir(dir);
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
    
    if(WEXITSTATUS(r)!= 0)
    {
        printf("Err en la descarga de drivers.");
        return -1;
    }
    return (WEXITSTATUS(r) == 0);
}

/* CHECK DMESG FOR ACTIVITY */
int mc_dmesg_has_activity(const char *driver)
{
    FILE *p = popen("dmesg | tail -n 30", "r");
    
    if (!p)
        return 0;

    char line[512];
    bool found = false;

    while (fgets(line, sizeof(line), p))
    {
        if (strstr(line, driver))
        {
            found = true;
            break;
        }
    }

    pclose(p);
    return found;
}

/* GET DEVICE SUBSYSTEM */
const char *mc_get_device_subsystem(const char *syspath)
{
    static char subsystem[16];
    char link_path[1024];
    char target[1024];

    snprintf(link_path, sizeof(link_path), "%s/subsystem", syspath);

    ssize_t len = readlink(link_path, target, sizeof(target) - 1);
    
    if (len == -1)
    {
        strcpy(subsystem, "unknown");
        return subsystem;
    }

    target[len] = '\0';

    const char *bus_name = strrchr(target, '/');
    if (!bus_name)
    {
        strcpy(subsystem, "unknown");
        return NULL;
    }
    
    size_t subsystem_len = strlen(bus_name) - strlen(syspath) - 1;
    
    if(subsystem_len > sizeof(subsystem) - 1)
        return NULL;
    
    strncpy(subsystem, bus_name + 1, subsystem_len);
    subsystem[subsystem_len] = '\0';
        
    return subsystem;
}

/* CHECK IF DEVICE HAS DRIVER BOUND */
int mc_dev_has_driver(const char *syspath)
{
    struct udev *udev = udev_new();
    if (!udev)
        return 0;

    struct udev_device *dev = udev_device_new_from_syspath(udev, syspath);
    if (!dev)
    {
        udev_unref(udev);
        return 0;
    }

    char driver_link[1024];
    snprintf(driver_link, sizeof(driver_link), "%s/driver", syspath);

    int has_driver = 0;
    if (access(driver_link, F_OK) == 0)
        has_driver = 1;
    

    udev_device_unref(dev);
    udev_unref(udev);
    return has_driver;
}

/* LIST ALL DEVICES (Multi-Bus Support) */
int mc_list_all_devices(mc_device_info_t *out, int max)
{
    struct udev *udev = udev_new();
    if (!udev)
        return 0;

    struct udev_enumerate *enumerate = udev_enumerate_new(udev);
    if (!enumerate)
    {
        udev_unref(udev);
        return 0;
    }

    // Add multiple subsystems to enumerate
    const char *subsystems[] = { "usb", "pci", "hid", "scsi", "pcmcia", NULL };
    for (int i = 0; subsystems[i]; i++)
        udev_enumerate_add_match_subsystem(enumerate, subsystems[i]);

    udev_enumerate_scan_devices(enumerate);

    struct udev_list_entry *devices = udev_enumerate_get_list_entry(enumerate);
    struct udev_list_entry *dev_list_entry;

    int count = 0;
    udev_list_entry_foreach(dev_list_entry, devices)
    {
        if (count >= max)
            break;

        const char *path = udev_list_entry_get_name(dev_list_entry);
        struct udev_device *dev = udev_device_new_from_syspath(udev, path);
        
        if (!dev)
            continue;

        const char *subsystem = udev_device_get_subsystem(dev);
        if (!subsystem)
        {
            udev_device_unref(dev);
            continue;
        }

        // Skip infrastructure devices
        if (mc_is_infrastructure_device(path, subsystem))
        {
            udev_device_unref(dev);
            continue;
        }

        // Variables comunes
        const char *vendor = NULL;
        const char *product = NULL;
        const char *model = NULL;
        const char *man_name = NULL;
        char combined_name[128];
        char vidpid[32] = "????:????";

        // USB Devices
        if (strcmp(subsystem, "usb") == 0)
        {
            const char *devtype = udev_device_get_devtype(dev);
            if (!devtype || strcmp(devtype, "usb_interface") != 0)
            {
                udev_device_unref(dev);
                continue;
            }

            // Skip Hubs
            const char *class_str = udev_device_get_sysattr_value(dev, "bInterfaceClass");
            if (class_str && strcmp(class_str, "09") == 0)
            {
                udev_device_unref(dev);
                continue;
            }

            // Parent device for USB metadata
            struct udev_device *parent = udev_device_get_parent_with_subsystem_devtype(dev, "usb", "usb_device");
            if (!parent)
            {
                udev_device_unref(dev);
                continue;
            }

            const char *p_class = udev_device_get_sysattr_value(parent, "bDeviceClass");
            if (p_class && strcmp(p_class, "09") == 0)
            {
                udev_device_unref(dev);
                continue;
            }

            vendor = udev_device_get_sysattr_value(parent, "idVendor");
            product = udev_device_get_sysattr_value(parent, "idProduct");
            const char *prod_name = udev_device_get_sysattr_value(parent, "product");
            man_name = udev_device_get_sysattr_value(parent, "manufacturer");
            const char *iface_num = udev_device_get_sysattr_value(dev, "bInterfaceNumber");

            snprintf(vidpid, sizeof(vidpid), "%s:%s", vendor ? vendor : "????", product ? product : "????");

            if (!prod_name)
                prod_name = "Unknown Device";
            if (!man_name)
                man_name = "";

            if (iface_num)
                snprintf(combined_name, sizeof(combined_name), "%s %s (If: %s)", man_name, prod_name, iface_num);
            else
                snprintf(combined_name, sizeof(combined_name), "%s %s", man_name, prod_name);

            strncpy(out[count].product, combined_name, 127);
        }
        // PCI Devices
        else if (strcmp(subsystem, "pci") == 0)
        {
            vendor = udev_device_get_sysattr_value(dev, "vendor");
            product = udev_device_get_sysattr_value(dev, "device");
            const char *label = udev_device_get_sysattr_value(dev, "label");
            const char *sysname = udev_device_get_sysname(dev);

            if (vendor && product)
                snprintf(vidpid, sizeof(vidpid), "%s:%s", vendor, product);

            if (label)
                strncpy(out[count].product, label, 127);
            else
                snprintf(out[count].product, 127, "PCI Device %s", sysname ? sysname : "Unknown");
        }
        // HID Devices
        else if (strcmp(subsystem, "hid") == 0)
        {
            strncpy(vidpid, "HID", sizeof(vidpid));
            const char *name = udev_device_get_sysattr_value(dev, "name");
            snprintf(out[count].product, 127, "HID: %s", name ? name : "HID Device");
        }
        // SCSI Devices
        else if (strcmp(subsystem, "scsi") == 0)
        {
            strncpy(vidpid, "SCSI", sizeof(vidpid));
            model = udev_device_get_sysattr_value(dev, "model");
            vendor = udev_device_get_sysattr_value(dev, "vendor");

            if (!vendor || !model)
                strncpy(out[count].product, "SCSI Device", 127);
            else
                snprintf(out[count].product, 127, "%s %s", vendor, model);
        }
        // PCMCIA Devices
        else if (strcmp(subsystem, "pcmcia") == 0)
        {
            const char *prod_id = udev_device_get_sysattr_value(dev, "prod_id");
            const char *manf_id = udev_device_get_sysattr_value(dev, "manf_id");
            const char *sysname = udev_device_get_sysname(dev);

            strncpy(vidpid, "PCMCIA", sizeof(vidpid));
            if (!prod_id)
                snprintf(out[count].product, 127, "PCMCIA Device %s", sysname ? sysname : "Unknown");
            else if (!manf_id)
                snprintf(out[count].product, 127, "PCMCIA: %s", prod_id);
            else
                snprintf(out[count].product, 127, "PCMCIA: %s %s", manf_id, prod_id);
        }
        else
        {
            // Unknown subsystem, skip
            udev_device_unref(dev);
            continue;
        }

        // Driver info (common)
        char driver_path[1024];
        char driver_target[1024];
        snprintf(driver_path, sizeof(driver_path), "%s/driver", path);
        ssize_t len = readlink(driver_path, driver_target, sizeof(driver_target) - 1);
        if (len != -1)
        {
            driver_target[len] = '\0';
            const char *dname = strrchr(driver_target, '/');
            const char *final_driver = dname ? dname + 1 : "unknown";

            // Skip USB host controllers
            if (strcmp(subsystem, "usb") == 0 &&
                (strstr(final_driver, "hcd") != NULL || strcmp(final_driver, "hub") == 0))
            {
                udev_device_unref(dev);
                continue;
            }

            strncpy(out[count].driver, final_driver, 63);
        }
        else
        {
            strncpy(out[count].driver, "None", 63);
        }

        // Fill common fields
        strncpy(out[count].syspath, path, 255);
        strncpy(out[count].vidpid, vidpid, 31);
        strncpy(out[count].subsystem, subsystem, 15);
        out[count].subsystem[15] = '\0';

        count++;
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

/*
 * Helper: Map module name to driver name
 * Some modules use different names in /sys/bus/.../drivers/
 */
static void get_driver_names(const char *module_name, char names[][128], int *count, int max_names)
{
    *count = 0;

    if (!module_name || *count >= max_names)
    {
        return;
    }

    // Always include the module name itself
    strncpy(names[*count], module_name, 127);
    names[*count][127] = '\0';
    (*count)++;

    // Known mappings for Realtek WiFi drivers
    if (strncmp(module_name, "rtw88_", 6) == 0 && *count < max_names)
    {
        // rtw88_8821cu → rtw_8821cu (without "88")
        const char *suffix = module_name + 6; // Skip "rtw88_"
        snprintf(names[*count], 128, "rtw_%s", suffix);
        (*count)++;
    }
    else if (strncmp(module_name, "rtl", 3) == 0 && *count < max_names)
    {
        // rtl8xxxu variants
        snprintf(names[*count], 128, "rtw_%s", module_name + 3);
        (*count)++;
    }
}

/*
 * Check if a driver is currently in use by checking for device bindings.
 * Checks both PCI and USB buses, and tries multiple name variants.
 * Returns 1 if in use, 0 otherwise.
 */
int mc_driver_is_in_use(const char *driver_name)
{
    if (!driver_name || driver_name[0] == '\0')
    {
        return 0;
    }

    // Get all possible driver name variants
    char driver_names[4][128];
    int name_count = 0;
    get_driver_names(driver_name, driver_names, &name_count, 4);

    // Try each name variant
    for (int n = 0; n < name_count; n++)
    {
        const char *current_name = driver_names[n];

        // Check PCI bus
        char pci_path[512];
        snprintf(pci_path, sizeof(pci_path), "/sys/bus/pci/drivers/%s", current_name);

        DIR *pci_dir = opendir(pci_path);
        if (pci_dir)
        {
            struct dirent *entry;
            while ((entry = readdir(pci_dir)) != NULL)
            {
                if (entry->d_name[0] == '.')
                    continue;

                // Skip special files
                if (strcmp(entry->d_name, "bind") == 0 ||
                    strcmp(entry->d_name, "unbind") == 0 ||
                    strcmp(entry->d_name, "uevent") == 0 ||
                    strcmp(entry->d_name, "module") == 0 ||
                    strcmp(entry->d_name, "new_id") == 0 ||
                    strcmp(entry->d_name, "remove_id") == 0)
                    continue;

                // Check if it's a symlink (device binding)
                char full_path[768];
                snprintf(full_path, sizeof(full_path), "%s/%s", pci_path, entry->d_name);

                struct stat sb;
                if (lstat(full_path, &sb) == 0 && S_ISLNK(sb.st_mode))
                {
                    closedir(pci_dir);
                    return 1;
                }
            }
            closedir(pci_dir);
        }

        // Check USB bus
        char usb_path[512];
        snprintf(usb_path, sizeof(usb_path), "/sys/bus/usb/drivers/%s", current_name);

        DIR *usb_dir = opendir(usb_path);
        if (usb_dir)
        {
            struct dirent *entry;
            while ((entry = readdir(usb_dir)) != NULL)
            {
                if (entry->d_name[0] == '.')
                    continue;

                // Skip special files
                if (strcmp(entry->d_name, "bind") == 0 ||
                    strcmp(entry->d_name, "unbind") == 0 ||
                    strcmp(entry->d_name, "uevent") == 0 ||
                    strcmp(entry->d_name, "module") == 0 ||
                    strcmp(entry->d_name, "new_id") == 0 ||
                    strcmp(entry->d_name, "remove_id") == 0)
                    continue;

                // Check if it's a symlink (device binding)
                char full_path[768];
                snprintf(full_path, sizeof(full_path), "%s/%s", usb_path, entry->d_name);

                struct stat sb;
                if (lstat(full_path, &sb) == 0 && S_ISLNK(sb.st_mode))
                {
                    closedir(usb_dir);
                    return 1;
                }
            }
            closedir(usb_dir);
        }

        // Check PCMCIA bus
        char pcmcia_path[512];
        snprintf(pcmcia_path, sizeof(pcmcia_path), "/sys/bus/pcmcia/drivers/%s", current_name);

        DIR *pcmcia_dir = opendir(pcmcia_path);
        if (pcmcia_dir)
        {
            struct dirent *entry;
            while ((entry = readdir(pcmcia_dir)) != NULL)
            {
                if (entry->d_name[0] == '.')
                    continue;

                // Skip special files
                if (strcmp(entry->d_name, "bind") == 0 ||
                    strcmp(entry->d_name, "unbind") == 0 ||
                    strcmp(entry->d_name, "uevent") == 0 ||
                    strcmp(entry->d_name, "module") == 0 ||
                    strcmp(entry->d_name, "new_id") == 0 ||
                    strcmp(entry->d_name, "remove_id") == 0)
                    continue;

                // Check if it's a symlink (device binding)
                char full_path[768];
                snprintf(full_path, sizeof(full_path), "%s/%s", pcmcia_path, entry->d_name);

                struct stat sb;
                if (lstat(full_path, &sb) == 0 && S_ISLNK(sb.st_mode))
                {
                    closedir(pcmcia_dir);
                    return 1;
                }
            }
            closedir(pcmcia_dir);
        }
    }

    // Check holders (module dependencies) - use original name
    char holders_path[512];
    snprintf(holders_path, sizeof(holders_path), "/sys/module/%s/holders", driver_name);

    DIR *holders_dir = opendir(holders_path);
    if (holders_dir)
    {
        struct dirent *entry;
        int has_holders = 0;

        while ((entry = readdir(holders_dir)) != NULL)
        {
            if (entry->d_name[0] != '.')
            {
                has_holders = 1;
                break;
            }
        }
        closedir(holders_dir);

        if (has_holders)
            return 1; // Has dependent modules
        
    }

    return 0;
}

/* CHECK IF DEVICE IS INFRASTRUCTURE (bridges, ports, hosts) */
/* Returns 1 if device is infrastructure that should be hidden, 0 if real endpoint */
int mc_is_infrastructure_device(const char *syspath, const char *subsystem)
{
    if (!syspath || !subsystem)
        return 0;

    struct udev *udev = udev_new();
    if (!udev)
        return 0;

    struct udev_device *dev = udev_device_new_from_syspath(udev, syspath);
    if (!dev)
    {
        udev_unref(udev);
        return 0;
    }

    /* PCI Infrastructure Filtering */
    if (strcmp(subsystem, "pci") == 0)
    {
        const char *class_str = udev_device_get_sysattr_value(dev, "class");
        if (class_str)
        {
            unsigned int class_code = 0;
            sscanf(class_str, "0x%x", &class_code);
            unsigned int base_class = (class_code >> 16) & 0xFF;
            unsigned int sub_class = (class_code >> 8) & 0xFF;

            /* Filter PCI infrastructure devices */
            if (base_class == 0x06) // Bridges
                return 1;
            if (base_class == 0x0c && sub_class == 0x05) // SMBus
                return 1;
            if (base_class == 0x08) // System Peripherals
                return 1;
        }

        /* Filter by driver name */
        char driver_path[1024], driver_target[1024];
        snprintf(driver_path, sizeof(driver_path), "%s/driver", syspath);
        ssize_t len = readlink(driver_path, driver_target, sizeof(driver_target) - 1);
        if (len != -1)
        {
            driver_target[len] = '\0';
            const char *driver_name = strrchr(driver_target, '/');
            if (!driver_name)
                return 1;

            driver_name++; // skip '/'

            const char *infra_drivers[] = {
                "pcieport", "pci_bridge", "pciehp", "pcie_aspm",
                "pcie_pme", "pcie_edr", "shpchp", "piix4_smbus", NULL};
            for (int i = 0; infra_drivers[i]; i++)
            {
                if (strcmp(driver_name, infra_drivers[i]) == 0)
                    return 1;
            }
        }
    }

    /* SCSI Infrastructure Filtering */
    if (strcmp(subsystem, "scsi") == 0)
    {
        const char *devtype = udev_device_get_devtype(dev);
        if (!devtype)
        {
            udev_device_unref(dev);
            udev_unref(udev);
            return 1;
        }

        if (strcmp(devtype, "scsi_host") == 0 ||
            strcmp(devtype, "scsi_target") == 0 ||
            strcmp(devtype, "scsi_generic") == 0)
        {
            udev_device_unref(dev);
            udev_unref(udev);
            return 1;
        }

        const char *model = udev_device_get_sysattr_value(dev, "model");
        const char *vendor = udev_device_get_sysattr_value(dev, "vendor");

        if (!model && !vendor)
        {
            udev_device_unref(dev);
            udev_unref(udev);
            return 1;
        }
    }

    udev_device_unref(dev);
    udev_unref(udev);
    return 0; // No infra detected
}

/* CHECK IF DEVICE SHOULD BE EXCLUDED (e.g. Mass Storage) */
int mc_is_excluded_device(const char *syspath)
{
    struct udev *udev = udev_new();
    if (!udev)
        return 0;

    struct udev_device *dev = udev_device_new_from_syspath(udev, syspath);

    if (!dev)
    {
        udev_unref(udev);
        return 0;
    }

    /* Check 1: bDeviceClass on device itself (rare for USB devices, usually 00) */
    const char *dclass = udev_device_get_sysattr_value(dev, "bDeviceClass");
    if (dclass && strcmp(dclass, "08") == 0)
    {
        udev_device_unref(dev);
        udev_unref(udev);
        return 1;
    }

    /* Check 2: bInterfaceClass on the interface (syspath points to interface) */
    const char *iclass = udev_device_get_sysattr_value(dev, "bInterfaceClass");
    if (iclass && strcmp(iclass, "08") == 0)
    {
        udev_device_unref(dev);
        udev_unref(udev);
        return 1;
    }

    /* Check 3: Walk up to parent to check device class if interface didn't match */
    struct udev_device *parent = udev_device_get_parent_with_subsystem_devtype(dev, "usb", "usb_device");
    if (parent)
    {
        const char *pclass = udev_device_get_sysattr_value(parent, "bDeviceClass");
        if (pclass && strcmp(pclass, "08") == 0)
        {
            udev_device_unref(dev);
            udev_unref(udev);
            return 1;
        }
    }

    udev_device_unref(dev);
    udev_unref(udev);
    return 0;
}
