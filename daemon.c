#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <libudev.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <signal.h>
#include <errno.h>

#include "heads/libmontecarlo.h"

#define SOCKET_PATH "/tmp/montecarlo.sock"

static int server_fd = -1;
static char current_syspath[1024] = {0};

/* Cleanup resources on exit */
void cleanup(int signum) {
    (void)signum;
    if (server_fd != -1) {
        close(server_fd);
    }
    unlink(SOCKET_PATH);
    exit(0);
}

/* Initialize Unix Domain Socket */
int init_socket() {
    struct sockaddr_un addr;

    if ((server_fd = socket(AF_UNIX, SOCK_STREAM, 0)) == -1) {
        perror("[daemon] socket error");
        return -1;
    }

    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, SOCKET_PATH, sizeof(addr.sun_path) - 1);

    unlink(SOCKET_PATH);

    if (bind(server_fd, (struct sockaddr*)&addr, sizeof(addr)) == -1) {
        perror("[daemon] bind error");
        return -1;
    }

    if (listen(server_fd, 5) == -1) {
        perror("[daemon] listen error");
        return -1;
    }
    
    /* Allow connections from any user (demo purpose) or restrict as needed */
    chmod(SOCKET_PATH, 0666);

    return 0;
}

/*
 * Handle client connection.
 * Simplified Protocol: Accept -> Send Target Syspath -> Close.
 */
void handle_client() {
    struct sockaddr_un client_addr;
    socklen_t len = sizeof(client_addr);
    int client_fd = accept(server_fd, (struct sockaddr*)&client_addr, &len);
    if (client_fd == -1) return;

    /* Send the current target syspath if available */
    if (current_syspath[0] != '\0') {
        char buf[1024];
        snprintf(buf, sizeof(buf), "{\"event\": \"add\", \"syspath\": \"%s\"}", current_syspath);
        send(client_fd, buf, strlen(buf), 0);
    } else {
        const char *msg = "{\"event\": \"none\"}";
        send(client_fd, msg, strlen(msg), 0);
    }

    close(client_fd);
}

int main()
{
    printf("[daemon] Starting Montecarlo Daemon...\n");

    signal(SIGINT, cleanup);
    signal(SIGTERM, cleanup);

    if (init_socket() == -1) {
        fprintf(stderr, "[daemon] Failed to init socket\n");
        return 1;
    }

    struct udev *udev = udev_new();
    if (!udev) {
        fprintf(stderr, "[daemon] udev_new failed\n");
        return 1;
    }

    struct udev_monitor *mon = udev_monitor_new_from_netlink(udev, "udev");
    if (!mon) {
        fprintf(stderr, "[daemon] udev_monitor failed\n");
        return 1;
    }

    udev_monitor_filter_add_match_subsystem_devtype(mon, "usb", NULL);
    udev_monitor_enable_receiving(mon);

    int udev_fd = udev_monitor_get_fd(mon);

    printf("[daemon] Listening on %s and UDev...\n", SOCKET_PATH);

    while (1) {
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(server_fd, &fds);
        FD_SET(udev_fd, &fds);

        int max_fd = (server_fd > udev_fd) ? server_fd : udev_fd;

        if (select(max_fd + 1, &fds, NULL, NULL, NULL) > 0) {
            
            /* 1. Incoming Socket Connection */
            if (FD_ISSET(server_fd, &fds)) {
                handle_client();
            }

            /* 2. Incoming UDev Event */
            if (FD_ISSET(udev_fd, &fds)) {
                struct udev_device *dev = udev_monitor_receive_device(mon);
                if (dev) {
                    const char *action = udev_device_get_action(dev);
                    const char *syspath = udev_device_get_syspath(dev);

                    if (action && strcmp(action, "add") == 0) {
                        printf("[daemon] add: %s\n", syspath);
                        
                        /* Check if the device already has a driver bound (ignoring interfaces) */
                        if (mc_dev_has_driver(syspath)) {
                            printf("[daemon] Driver already present. Ignoring.\n");
                            current_syspath[0] = '\0';
                        } else {
                            printf("[daemon] No driver found. Triggering UI.\n");
                            strncpy(current_syspath, syspath, sizeof(current_syspath) - 1);
                            
                            /* Launch the User Interface */
                            pid_t pid = fork();
                            if (pid == 0) {
                                /* Child Process */
                                setenv("DISPLAY", ":0", 0); /* Hack for demo environment */
                                
                                /* Path Logic */
                                if (getenv("MONTECARLO_DEV")) {
                                    /* Dev Mode: ui.py in cwd */
                                    printf("[daemon] Launching UI in DEV mode (cwd)\n");
                                    execlp("python3", "python3", "ui.py", NULL);
                                } else {
                                    /* Prod Mode: ui.py in /usr/share/montecarlo */
                                    /* We call python3 directly on the full path */
                                    execlp("python3", "python3", "/usr/share/montecarlo/ui.py", NULL);
                                }
                                
                                /* If execlp returns, it failed */
                                perror("[daemon] execlp failed");
                                exit(1);
                            } else {
                                /* Parent Process: Continue monitoring */
                            }
                        }
                    } else if (action && strcmp(action, "remove") == 0) {
                         if (syspath && strcmp(syspath, current_syspath) == 0) {
                             current_syspath[0] = '\0';
                         }
                    }
                    udev_device_unref(dev);
                }
            }
        }
    }

    udev_unref(udev);
    return 0;
}
