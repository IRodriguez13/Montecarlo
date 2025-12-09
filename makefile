CC = gcc
CFLAGS = -Wall -Wextra -fPIC -I.
LDFLAGS = -ludev 
TARGET_LIB = libmontecarlo.so
TARGET_DAEMON = montecarlo-daemon
TARGET_CLI = montecarlo_cli
TARGET_HELPER = montecarlo-helper

# Standard Install Paths
PREFIX ?= /usr
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib
SHAREDIR ?= $(PREFIX)/share/montecarlo
INCLUDEDIR ?= $(PREFIX)/include/montecarlo
MANDIR ?= $(PREFIX)/share/man
POLICYDIR ?= $(PREFIX)/share/polkit-1/actions

all: $(TARGET_LIB) $(TARGET_DAEMON) $(TARGET_CLI) $(TARGET_HELPER)

# Library
$(TARGET_LIB): libmontecarlo.c
	$(CC) $(CFLAGS) -shared -o $@ $^ $(LDFLAGS)

# Daemon (Production: No RPATH, expects lib in /usr/lib)
$(TARGET_DAEMON): daemon.c $(TARGET_LIB)
	$(CC) $(CFLAGS) -o $@ daemon.c -L. -lmontecarlo $(LDFLAGS)

# CLI (Production)
$(TARGET_CLI): montecarlo.c cache.c $(TARGET_LIB)
	$(CC) $(CFLAGS) -o $@ montecarlo.c cache.c -L. -lmontecarlo $(LDFLAGS)

# Helper (PolicyKit)
$(TARGET_HELPER): helper.c
	$(CC) $(CFLAGS) -o $@ $^

# Developer Targets (With RPATH for local run)
dev: CFLAGS += -g
dev: clean $(TARGET_LIB) $(TARGET_HELPER)
	$(CC) $(CFLAGS) -o $(TARGET_DAEMON) daemon.c -L. -lmontecarlo $(LDFLAGS) -Wl,-rpath=.
	$(CC) $(CFLAGS) -o $(TARGET_CLI) montecarlo.c cache.c -L. -lmontecarlo $(LDFLAGS) -Wl,-rpath=.
	@echo "Built for local development (RPATH set)."
	@echo "Launching UI..."
	MONTECARLO_DEV=1 python3 ui.py

install: all
	install -d $(DESTDIR)$(BINDIR)
	install -d $(DESTDIR)$(LIBDIR)
	install -d $(DESTDIR)$(SHAREDIR)
	install -d $(DESTDIR)$(INCLUDEDIR)
	install -d $(DESTDIR)$(MANDIR)/man1
	install -d $(DESTDIR)$(MANDIR)/man8
	install -d $(DESTDIR)$(POLICYDIR)
	
	# Binaries
	install -m 755 $(TARGET_DAEMON) $(DESTDIR)$(BINDIR)/$(TARGET_DAEMON)
	install -m 755 $(TARGET_CLI) $(DESTDIR)$(BINDIR)/$(TARGET_CLI)
	install -m 755 $(TARGET_HELPER) $(DESTDIR)$(BINDIR)/$(TARGET_HELPER)
	
	# Library and UI
	install -m 644 $(TARGET_LIB) $(DESTDIR)$(LIBDIR)/$(TARGET_LIB)
	install -m 755 ui.py $(DESTDIR)$(SHAREDIR)/ui.py
	install -m 644 heads/libmontecarlo.h $(DESTDIR)$(INCLUDEDIR)/libmontecarlo.h
	
	# Man pages
	gzip -c man/montecarlo.1 > $(DESTDIR)$(MANDIR)/man1/montecarlo.1.gz
	gzip -c man/montecarlo-daemon.8 > $(DESTDIR)$(MANDIR)/man8/montecarlo-daemon.8.gz
	
	# PolicyKit
	install -m 644 org.montecarlo.policy $(DESTDIR)$(POLICYDIR)/org.montecarlo.policy

clean:
	rm -f $(TARGET_LIB) $(TARGET_DAEMON) $(TARGET_CLI) $(TARGET_HELPER) *.o

.PHONY: all clean install dev
