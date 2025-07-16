# Simple Makefile for building crashy
CC = gcc
CFLAGS = -g -O0 -Wall

all: crashy

crashy: crashy.c
	$(CC) $(CFLAGS) -o crashy crashy.c

clean:
	rm -f crashy *.o

.PHONY: all clean