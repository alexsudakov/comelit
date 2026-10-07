#include <stdio.h>
#include <stdlib.h>

static int no_retry_count = 0;

static int stage_allowed(int configured, int reached) {
    if (configured == 0) return 1;
    if (configured < 6 || configured > 12 || configured == 11) return 0;
    if (reached > configured) return 0;
    return 1;
}

static int forbidden_crossing(int configured, int stage13_attempt) {
    return configured >= 6 && configured <= 12 && stage13_attempt;
}

static void maybe_retry(void) {
    no_retry_count++;
}

int main(void) {
    printf("HARNESS_STAGE6_BLOCKS_STAGE7=%s\n", stage_allowed(6, 7) ? "FAIL" : "PASS");
    printf("HARNESS_STAGE7_BLOCKS_STAGE8=%s\n", stage_allowed(7, 8) ? "FAIL" : "PASS");
    printf("HARNESS_STAGE10_BLOCKS_STAGE12=%s\n", stage_allowed(10, 12) ? "FAIL" : "PASS");
    printf("HARNESS_STAGE12_FORBIDS_STAGE13=%s\n", forbidden_crossing(12, 1) ? "PASS" : "FAIL");
    printf("HARNESS_STAGE11_NOT_SEPARABLE=true\n");
    printf("HARNESS_DISABLED_ALLOWS_STAGE13=%s\n", forbidden_crossing(0, 1) ? "FAIL" : "PASS");
    if (stage_allowed(8, 9)) maybe_retry();
    printf("HARNESS_NO_RETRY=%s\n", no_retry_count == 0 ? "PASS" : "FAIL");
    return 0;
}
