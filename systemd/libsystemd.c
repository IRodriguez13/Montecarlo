#include <stdio.h>
#include <string.h>
#include <systemd/sd-bus.h>

#include "libsystemd.h"

/* List services and fill struct array */
int mc_list_services(service_info_t *out, int max_count)
{
    sd_bus_message *m = NULL;
    sd_bus_error err = SD_BUS_ERROR_NULL;
    sd_bus *bus = NULL;
    int count = 0;
    int r;

    r = sd_bus_open_system(&bus);
    if (r < 0)
    {
        return 0;
    }

    /* ListUnits returns array of structs */
    r = sd_bus_call_method(
        bus,
        "org.freedesktop.systemd1",
        "/org/freedesktop/systemd1",
        "org.freedesktop.systemd1.Manager",
        "ListUnits",
        &err,
        &m,
        NULL);

    if (r < 0)
    {
        sd_bus_error_free(&err);
        sd_bus_unref(bus);
        return 0;
    }

    r = sd_bus_message_enter_container(m, SD_BUS_TYPE_ARRAY, "(ssssssouso)");
    if (r < 0) goto finish;
    
    while ((r = sd_bus_message_enter_container(m, SD_BUS_TYPE_STRUCT, "ssssssouso")) > 0)
    {
        if (count >= max_count)
        {
            sd_bus_message_exit_container(m); // Exit current struct
            break;
        }

        const char *name, *desc, *load, *active, *sub, *following;
        const char *obj_path, *job_type, *job_path;
        uint32_t job_id;

        sd_bus_message_read(
            m,
            "ssssssouso",
            &name,
            &desc,
            &load,
            &active,
            &sub,
            &following,
            &obj_path,
            &job_id,
            &job_type,
            &job_path);

        // Filter: only .service units
        if (strstr(name, ".service"))
        {
            strncpy(out[count].name, name, SERVICE_NAME_MAX - 1);
            strncpy(out[count].description, desc, SERVICE_DESC_MAX - 1);
            strncpy(out[count].state, active, 31);
            strncpy(out[count].sub_state, sub, 31);
            
            out[count].name[SERVICE_NAME_MAX - 1] = '\0';
            out[count].description[SERVICE_DESC_MAX - 1] = '\0';
            out[count].state[31] = '\0';
            out[count].sub_state[31] = '\0';
            
            count++;
        }

        sd_bus_message_exit_container(m);
    }

    sd_bus_message_exit_container(m); // Exit array

    finish:
        sd_bus_error_free(&err);
        sd_bus_message_unref(m);
        sd_bus_unref(bus);

    return count;
}

// Keep for backward compat/debug
void list_active_services()
{
    service_info_t services[100];
    int c = mc_list_services(services, 100);
    for(int i=0; i<c; i++) {
        if(strcmp(services[i].state, "active") == 0)
            printf("%s (%s)\n", services[i].name, services[i].sub_state);
    }
}


int systemd_start_service(const char *name)
{
    sd_bus *bus = NULL;
    sd_bus_error error = SD_BUS_ERROR_NULL;
    int r;

    r = sd_bus_open_system(&bus);
    if (r < 0)
        return r;

    r = sd_bus_call_method(
        bus,
        "org.freedesktop.systemd1",
        "/org/freedesktop/systemd1",
        "org.freedesktop.systemd1.Manager",
        "StartUnit",
        &error,
        NULL,
        "ss",
        name,
        "replace"
    );

    sd_bus_error_free(&error);
    sd_bus_unref(bus);

    return r;
}

int systemd_enable_service(const char *name)
{
    sd_bus *bus = NULL;
    sd_bus_error error = SD_BUS_ERROR_NULL;
    int r;

    r = sd_bus_open_system(&bus);
    if (r < 0)
        return r;

    r = sd_bus_call_method(
        bus,
        "org.freedesktop.systemd1",
        "/org/freedesktop/systemd1",
        "org.freedesktop.systemd1.Manager",
        "EnableUnitFiles",
        &error,
        NULL,
        "asbb",
        1, &name,
        0, /* runtime */
        1  /* force */
    );

    sd_bus_error_free(&error);
    sd_bus_unref(bus);

    return r;
}

int systemd_stop_service(const char *name)
{
    sd_bus *bus = NULL;
    sd_bus_error error = SD_BUS_ERROR_NULL;
    int r;

    r = sd_bus_open_system(&bus);
    if (r < 0)
        return r;

    r = sd_bus_call_method(
        bus,
        "org.freedesktop.systemd1",
        "/org/freedesktop/systemd1",
        "org.freedesktop.systemd1.Manager",
        "StopUnit",
        &error,
        NULL,
        "ss",
        name,
        "replace"
    );

    sd_bus_error_free(&error);
    sd_bus_unref(bus);

    return r;
}

int systemd_disable_service(const char *name)
{
    sd_bus *bus = NULL;
    sd_bus_error error = SD_BUS_ERROR_NULL;
    int r;

    r = sd_bus_open_system(&bus);
    if (r < 0)
        return r;

    r = sd_bus_call_method(
        bus,
        "org.freedesktop.systemd1",
        "/org/freedesktop/systemd1",
        "org.freedesktop.systemd1.Manager",
        "DisableUnitFiles",
        &error,
        NULL,
        "asb",
        1, &name,
        0 /* runtime */
    );

    sd_bus_error_free(&error);
    sd_bus_unref(bus);

    return r;
}

