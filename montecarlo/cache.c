#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define CACHE_PATH "/var/lib/ir0-usb/cache.json"

// Guarda: "vendor:product" -> driver
int cache_save(const char *vendor, const char *product, const char *driver)
{
    FILE *f = fopen(CACHE_PATH, "a");
    if (!f)
    {
        return 0;
    }

    time_t t = time(NULL);

    fprintf(f,"{ \"%s:%s\": { \"driver\": \"%s\", \"seen\": \"%ld\" } }\n", vendor, product, driver, t);

    fclose(f);
    return 1;
}
