CC = gcc
CFLAGS = -Wall -Wextra -fPIC -I.
LDFLAGS = -ludev 
TARGET_LIB = libmontecarlo.so
TARGET_DAEMON = montecarlo-daemon
TARGET_CLI = montecarlo_cli

all: $(TARGET_LIB) $(TARGET_DAEMON) $(TARGET_CLI)

$(TARGET_LIB): libmontecarlo.c
	$(CC) $(CFLAGS) -shared -o $@ $^ $(LDFLAGS)

$(TARGET_DAEMON): daemon.c $(TARGET_LIB)
	$(CC) $(CFLAGS) -o $@ daemon.c -L. -lmontecarlo $(LDFLAGS) -Wl,-rpath=.

# Keeping the old CLI for reference or debugging, linked against the lib now maybe?
# Or just keeping it as is but using the lib source.
# Let's link it to the lib to reuse code.
$(TARGET_CLI): montecarlo.c cache.c $(TARGET_LIB)
	$(CC) $(CFLAGS) -o $@ montecarlo.c cache.c -L. -lmontecarlo $(LDFLAGS) -Wl,-rpath=.

clean:
	rm -f $(TARGET_LIB) $(TARGET_DAEMON) $(TARGET_CLI) *.o
