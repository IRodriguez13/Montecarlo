CC = gcc
CFLAGS = -Wall -Wextra -fPIC -I. -Imontecarlo
LDFLAGS = -ludev

# -------- Targets --------
TARGET_LIB = libmontecarlo.so
TARGET_DAEMON = montecarlo-daemon
TARGET_CLI = montecarlo_cli
TARGET_HELPER = montecarlo-helper

# -------- systemd sublib --------
SYSTEMD_DIR = systemd
SYSTEMD_LIB = libsystemdctl.so
SYSTEMD_LIB_PATH = $(SYSTEMD_DIR)/$(SYSTEMD_LIB)
SYSTEMD_LIBS = -lsystemd

# -------- Install paths --------
PREFIX ?= /usr
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib
SHAREDIR ?= $(PREFIX)/share/montecarlo
INCLUDEDIR ?= $(PREFIX)/include/montecarlo
MANDIR ?= $(PREFIX)/share/man
POLICYDIR ?= $(PREFIX)/share/polkit-1/actions

# -------- Default target --------
all: $(SYSTEMD_LIB_PATH) $(TARGET_LIB) $(TARGET_DAEMON) $(TARGET_CLI) $(TARGET_HELPER)

# -------- systemd library --------
$(SYSTEMD_LIB_PATH): $(SYSTEMD_DIR)/libsystemd.c $(SYSTEMD_DIR)/libsystemd.h
	$(CC) $(CFLAGS) -shared -o $@ $< $(SYSTEMD_LIBS)

# -------- Main library --------
$(TARGET_LIB): montecarlo/libmontecarlo.c
	$(CC) $(CFLAGS) -shared -o $@ $^ $(LDFLAGS)

# -------- Daemon (production) --------
$(TARGET_DAEMON): daemon.c $(TARGET_LIB) $(SYSTEMD_LIB_PATH)
	$(CC) $(CFLAGS) -o $@ daemon.c \
	    -L. -lmontecarlo \
	    -L$(SYSTEMD_DIR) -lsystemdctl \
	    $(LDFLAGS) $(SYSTEMD_LIBS)

# -------- CLI (production) --------
$(TARGET_CLI): montecarlo/montecarlo.c montecarlo/cache.c $(TARGET_LIB) $(SYSTEMD_LIB_PATH)
	$(CC) $(CFLAGS) -o $@ montecarlo/montecarlo.c montecarlo/cache.c \
	    -L. -lmontecarlo \
	    -L$(SYSTEMD_DIR) -lsystemdctl \
	    $(LDFLAGS) $(SYSTEMD_LIBS)

# -------- Helper (PolicyKit) --------
# -------- Helper (PolicyKit) --------
$(TARGET_HELPER): montecarlo/helper.c $(SYSTEMD_LIB_PATH)
	$(CC) $(CFLAGS) -o $@ montecarlo/helper.c \
	    -L$(SYSTEMD_DIR) -lsystemdctl \
	    $(SYSTEMD_LIBS) \
	    -Wl,-rpath=$(DESTDIR)$(LIBDIR):$(SYSTEMD_DIR)

# -------- Dev build (with RPATH) --------
dev: CFLAGS += -g
dev: clean $(SYSTEMD_LIB_PATH) $(TARGET_LIB) $(TARGET_HELPER)
	$(CC) $(CFLAGS) -o $(TARGET_DAEMON) daemon.c \
	    -L. -lmontecarlo \
	    -L$(SYSTEMD_DIR) -lsystemdctl \
	    $(LDFLAGS) $(SYSTEMD_LIBS) \
	    -Wl,-rpath=.:$(SYSTEMD_DIR)

	$(CC) $(CFLAGS) -o $(TARGET_CLI) montecarlo/montecarlo.c montecarlo/cache.c \
	    -L. -lmontecarlo \
	    -L$(SYSTEMD_DIR) -lsystemdctl \
	    $(LDFLAGS) $(SYSTEMD_LIBS) \
	    -Wl,-rpath=.:$(SYSTEMD_DIR)

	@echo "Built for local development (RPATH set)."
	@echo "Launching UI..."
	MONTECARLO_DEV=1 python3 ui.py

# -------- Install --------
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

	# Libraries
	install -m 644 $(TARGET_LIB) $(DESTDIR)$(LIBDIR)/$(TARGET_LIB)
	install -m 644 $(SYSTEMD_LIB_PATH) $(DESTDIR)$(LIBDIR)/$(SYSTEMD_LIB)

	# Headers
	install -m 644 heads/libmontecarlo.h $(DESTDIR)$(INCLUDEDIR)/libmontecarlo.h
	install -m 644 $(SYSTEMD_DIR)/libsystemdctl.h $(DESTDIR)$(INCLUDEDIR)/libsystemdctl.h

	# UI
	install -m 755 ui.py $(DESTDIR)$(SHAREDIR)/ui.py

	# Man pages
	gzip -c man/montecarlo.1 > $(DESTDIR)$(MANDIR)/man1/montecarlo.1.gz
	gzip -c man/montecarlo-daemon.8 > $(DESTDIR)$(MANDIR)/man8/montecarlo-daemon.8.gz

	# PolicyKit
	install -m 644 org.montecarlo.policy $(DESTDIR)$(POLICYDIR)/org.montecarlo.policy

# -------- Clean --------
clean:
	rm -f \
	    $(TARGET_LIB) \
	    $(TARGET_DAEMON) \
	    $(TARGET_CLI) \
	    $(TARGET_HELPER) \
	    $(SYSTEMD_LIB_PATH) \
	    *.o

.PHONY: all clean install dev
