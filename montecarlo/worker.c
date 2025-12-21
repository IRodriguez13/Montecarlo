#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libudev.h>

int main(int argc, char *argv[])
{
    if (argc < 2)
    {
        fprintf(stderr, "Uso: worker <devpath>\n");
        return 1;
    }

    const char *devpath = argv[1];

    struct udev *udev = udev_new();
    if (!udev)
    {
        fprintf(stderr, "[worker] error creando udev\n");
        return 1;
    }

    // Tomamos el device real desde la ruta completa
    struct udev_device *dev =
        udev_device_new_from_syspath(udev, devpath);

    if (!dev)
    {
        fprintf(stderr, "[worker] no pude obtener info udev para %s\n", devpath);
        udev_unref(udev);
        return 1;
    }

    // Subir por la jerarquía hasta encontrar el dispositivo USB real
    struct udev_device *usb = dev;
    while (usb && strcmp(udev_device_get_subsystem(usb), "usb") != 0)
    {
        usb = udev_device_get_parent(usb);
    }

    if (!usb)
    {
        fprintf(stderr, "[worker] no encontré nodo USB padre\n");
        udev_device_unref(dev);
        udev_unref(udev);
        return 1;
    }

    // Leer atributos directamente desde sysfs via udev
    const char *vendor = udev_device_get_sysattr_value(usb, "idVendor");
    const char *product = udev_device_get_sysattr_value(usb, "idProduct");

    if (!vendor)
        vendor = "(unknown)";

    if (!product)
        product = "(unknown)";


    printf("[worker] iniciado para: %s\n", devpath);
    printf("[worker] vendor:  %s\n", vendor);
    printf("[worker] product: %s\n", product);

    udev_device_unref(dev);
    udev_unref(udev);

    return 0;
}
