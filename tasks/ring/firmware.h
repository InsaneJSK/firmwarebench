#ifndef FIRMWARE_H
#define FIRMWARE_H
#include <stdint.h>
#define CAPACITY 4
typedef struct { uint8_t data[CAPACITY]; unsigned head, tail, count; } Ring;
void put(Ring *r, uint8_t sample);
int take(Ring *r);
#endif
