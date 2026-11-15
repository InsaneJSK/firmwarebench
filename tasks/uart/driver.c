#include "firmware.h"
#include <stdio.h>

/* One line per read operation. A reset starts a new stream. */
static void emit(uint8_t ch, uint8_t value) { printf("%u,%u ", ch, value); }
int main(void) {
    Parser parser = {0};
    char line[520];
    while (fgets(line, sizeof line, stdin)) {
        if (line[0] == '!') { parser = (Parser){0}; continue; }
        uint8_t bytes[256];
        unsigned n = 0, value = 0;
        for (unsigned i = 0; line[i] && line[i] != '\n' && line[i] != '\r'; i += 2) {
            if (n == sizeof bytes || sscanf(line + i, "%2x", &value) != 1) return 2;
            bytes[n++] = (uint8_t)value;
        }
        feed(&parser, bytes, n, emit);
        puts("|");
    }
    return 0;
}
