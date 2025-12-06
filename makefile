CC = gcc
CFLAGS = -Wall -Wextra -O2
LIBS = -ludev

TARGETS = daemon worker montecarlo_cli

all: $(TARGETS)

daemon: daemon.c dev.o cache.o
	$(CC) $(CFLAGS) -o daemon daemon.c dev.o cache.o $(LIBS)

worker: worker.c dev.o cache.o
	$(CC) $(CFLAGS) -o worker worker.c dev.o cache.o $(LIBS)

montecarlo_cli: montecarlo.c dev.o cache.o
	$(CC) $(CFLAGS) -o montecarlo_cli montecarlo.c dev.o cache.o $(LIBS)

dev.o: heads/dev.h dev.c
	$(CC) $(CFLAGS) -c dev.c

cache.o: heads/cache.h cache.c
	$(CC) $(CFLAGS) -c cache.c

clean:
	rm -f *.o $(TARGETS)

.PHONY: all clean
