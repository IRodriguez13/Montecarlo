#ifndef LIBMONTECARLO_H
#define LIBMONTECARLO_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stddef.h>

// Core Driver Operations
int mc_read_sysattr(const char *path, char *buf, size_t buflen);
void mc_get_ids(const char *syspath, char *vendor, char *product);
int mc_list_candidate_drivers(char out[][128], int max);
int mc_try_load_driver(const char *driver);
void mc_unload_driver(const char *driver);
int mc_dmesg_has_activity(const char *driver);

// High level checks
int mc_dev_has_driver(const char *syspath);

#ifdef __cplusplus
}
#endif

#endif // LIBMONTECARLO_H
