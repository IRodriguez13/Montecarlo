#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include <stddef.h>

/*Core Driver Operations*/
int mc_read_sysattr(const char *path, char *buf, size_t buflen);
void mc_get_ids(const char *syspath, char *vendor, char *product);
int mc_list_candidate_drivers(char out[][128], int max);

typedef struct {
    char syspath[256];
    char vidpid[32];
    char product[128];
    char driver[64];
    char subsystem[16];
} mc_device_info_t;

int mc_list_all_devices(mc_device_info_t *out, int max);
const char* mc_get_device_subsystem(const char *syspath);
int mc_try_load_driver(const char *driver);
int mc_unload_driver(const char *driver);
int mc_dmesg_has_activity(const char *driver);
int mc_dmesg_has_activity(const char *driver);
int mc_module_has_holders(const char *module);
int mc_get_module_refcount(const char *module);
int mc_list_loaded_modules(char *out_buf, int max_size);
int mc_driver_is_in_use(const char *driver);

/*High level checks*/
int mc_dev_has_driver(const char *syspath);
int mc_is_excluded_device(const char *syspath);
int mc_is_infrastructure_device(const char *syspath, const char *subsystem);



#ifdef __cplusplus
}
#endif
