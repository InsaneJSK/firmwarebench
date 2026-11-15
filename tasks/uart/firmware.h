#ifndef FIRMWARE_H
#define FIRMWARE_H
#include <stdint.h>

/* Frames are 0xA5, channel, value. Any byte is legal in the payload. */
typedef struct { unsigned used; uint8_t payload[2]; } Parser;
typedef void (*Emit)(uint8_t channel, uint8_t value);
void feed(Parser *p, const uint8_t *bytes, unsigned count, Emit emit);
#endif
