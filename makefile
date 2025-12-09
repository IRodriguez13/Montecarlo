CC = gcc
CFLAGS = -Wall -Wextra -fPIC -I.
LDFLAGS = -ludev 
TARGET_LIB = libmontecarlo.so
TARGET_DAEMON = montecarlo-daemon
TARGET_CLI = montecarlo_cli

# Standard Install Paths
PREFIX ?= /usr
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib
SHAREDIR ?= $(PREFIX)/share/montecarlo
INCLUDEDIR ?= $(PREFIX)/include/montecarlo

all: $(TARGET_LIB) $(TARGET_DAEMON) $(TARGET_CLI)

# Library
$(TARGET_LIB): libmontecarlo.c
	$(CC) $(CFLAGS) -shared -o $@ $^ $(LDFLAGS)

# Daemon (Production: No RPATH, expects lib in /usr/lib)
$(TARGET_DAEMON): daemon.c $(TARGET_LIB)
	$(CC) $(CFLAGS) -o $@ daemon.c -L. -lmontecarlo $(LDFLAGS)

# CLI (Production)
$(TARGET_CLI): montecarlo.c cache.c $(TARGET_LIB)
	$(CC) $(CFLAGS) -o $@ montecarlo.c cache.c -L. -lmontecarlo $(LDFLAGS)

# Developer Targets (With RPATH for local run)
dev: CFLAGS += -g
dev: clean $(TARGET_LIB)
	$(CC) $(CFLAGS) -o $(TARGET_DAEMON) daemon.c -L. -lmontecarlo $(LDFLAGS) -Wl,-rpath=.
	$(CC) $(CFLAGS) -o $(TARGET_CLI) montecarlo.c cache.c -L. -lmontecarlo $(LDFLAGS) -Wl,-rpath=.
	@echo "Built for local development (RPATH set)."

install: all
	install -d $(DESTDIR)$(BINDIR)
	install -d $(DESTDIR)$(LIBDIR)
	install -d $(DESTDIR)$(SHAREDIR)
	install -d $(DESTDIR)$(INCLUDEDIR)
	
	install -m 755 $(TARGET_DAEMON) $(DESTDIR)$(BINDIR)/$(TARGET_DAEMON)
	install -m 755 $(TARGET_CLI) $(DESTDIR)$(BINDIR)/$(TARGET_CLI)
	install -m 644 $(TARGET_LIB) $(DESTDIR)$(LIBDIR)/$(TARGET_LIB)
	install -m 644 ui.py $(DESTDIR)$(SHAREDIR)/ui.py
	install -m 644 heads/libmontecarlo.h $(DESTDIR)$(INCLUDEDIR)/libmontecarlo.h

clean:
	rm -f $(TARGET_LIB) $(TARGET_DAEMON) $(TARGET_CLI) *.o

.PHONY: all clean install dev
