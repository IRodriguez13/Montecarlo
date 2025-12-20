#pragma once

#define SERVICE_NAME_MAX 256
#define SERVICE_DESC_MAX 512

typedef struct
{
    char name[SERVICE_NAME_MAX];
    char description[SERVICE_DESC_MAX];
    char state[32];         // active, inactive, failed
    char sub_state[32];     // running, exited, dead
} service_info_t;

/* List services. Returns count of services found. */
int mc_list_services(service_info_t *out, int max_count);

void list_active_services();
int systemd_start_service(const char *name);
int systemd_stop_service(const char *name);
int systemd_restart_service(const char *name);
int systemd_enable_service(const char *name);
int systemd_disable_service(const char *name);
