#include "firmware.h"
#include <stdio.h>

int main(void) {
    Ring r = {0};
    char line[32];
    while (fgets(line, sizeof line, stdin)) {
        unsigned value;
        if (line[0] == '!') r = (Ring){0};
        else if (line[0] == '-') printf("%d\n", take(&r));
        else if (sscanf(line, "+%u", &value) == 1) put(&r, (uint8_t)value);
        else return 2;
    }
    return 0;
}
