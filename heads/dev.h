#pragma once 
#include <stdbool.h>
#include <libudev.h>

bool dev_has_driver(struct udev_device *dev);
