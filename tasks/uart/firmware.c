#include "firmware.h"

void feed(Parser *p, const uint8_t *bytes, unsigned count, Emit emit) {
    p->used = 0;
    for (unsigned i = 0; i < count; ++i) {
        if (p->used == 0) {
            if (bytes[i] == 0xA5) p->used = 1;
        } else {
            p->payload[p->used - 1] = bytes[i];
            if (++p->used == 3) {
                emit(p->payload[0], p->payload[1]);
                p->used = 0;
            }
        }
    }
}
