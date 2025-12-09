#pragma once

int dmesg_has_activity(const char *driver);
int try_load_driver(const char *driver);
void launch_ui(const char *vendor, const char *product);
int read_sysattr(const char *path, char *buf, size_t buflen);
void get_ids(const char *syspath, char *vendor, char *product);
int list_candidate_drivers(char out[][128], int max);
