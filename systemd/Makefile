CC = gcc
CFLAGS = -Wall -Wextra -O2 -fPIC
LDFLAGS = -shared
LIBS = -lsystemd

TARGET = libsystemdctl.so

lsystemd: $(TARGET)

$(TARGET): libsystemd.o
	$(CC) $(LDFLAGS) -o $@ $^ $(LIBS)

libsystemd.o: libsystemd.c libsystemd.h
	$(CC) $(CFLAGS) -c libsystemd.c

clean:
	rm -f *.o $(TARGET)
