#include <stdio.h>
#include <stdbool.h>
#include <libudev.h>
#include <string.h>

bool dev_has_driver(struct udev_device *dev)
{
    if (!dev)
        return false;
    

    struct udev_device *parent = dev;
    const char *sub;

    while ((sub = udev_device_get_subsystem(parent)) &&
           strcmp(sub, "usb") != 0)
    {
        struct udev_device *p = udev_device_get_parent(parent);
        if (!p)
            break;
        
        parent = p;
    }

    if (!parent)
        return false;


    const char *driver = udev_device_get_driver(parent);

    if (driver)
    {
        printf("[dev] driver encontrado: %s\n", driver);
        return true;
    }

    printf("[dev] no hay driver\n");
    return false;
}
