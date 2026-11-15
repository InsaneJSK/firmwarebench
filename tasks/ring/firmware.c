#include "firmware.h"

void put(Ring *r, uint8_t sample) {
    if (r->count == CAPACITY) return;
    r->data[r->head] = sample;
    r->head = (r->head + 1) % CAPACITY;
    ++r->count;
}

int take(Ring *r) {
    if (r->count == 0) return -1;
    int sample = r->data[r->tail];
    r->tail = (r->tail + 1) % CAPACITY;
    --r->count;
    return sample;
}
