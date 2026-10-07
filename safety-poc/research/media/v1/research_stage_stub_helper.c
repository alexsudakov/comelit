#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static volatile sig_atomic_t term_seen = 0;

static void on_term(int signum) {
    (void)signum;
    term_seen = 1;
}

static int emit_until_stage(int stage) {
    puts("RESEARCH_STAGE_6_LOCAL_OFFER_READY");
    fflush(stdout);
    if (stage == 6) return 0;
    puts("RESEARCH_STAGE_7_BACKEND_P2P_ALLOCATED");
    fflush(stdout);
    if (stage == 7) return 0;
    puts("RESEARCH_STAGE_8_REMOTE_SDP_APPLIED");
    fflush(stdout);
    if (stage == 8) return 0;
    puts("RESEARCH_STAGE_9_ICE_CONNECTED");
    fflush(stdout);
    if (stage == 9) return 0;
    puts("RESEARCH_STAGE_10_PSEUDOTCP_OPEN");
    fflush(stdout);
    if (stage == 10) return 0;
    puts("RESEARCH_STAGE_11_CTPP_PRE_REGISTER");
    fflush(stdout);
    puts("STAGE_11_NOT_SEPARABLE=true");
    puts("RESEARCH_STAGE_12_CTPP_REGISTERED");
    fflush(stdout);
    if (stage == 12) return 0;
    return 1;
}

int main(void) {
    const char *stop_env = getenv("RESEARCH_STOP_AFTER_STAGE");
    const char *hold_env = getenv("RESEARCH_HOLD_MS");
    const char *forbidden = getenv("RESEARCH_FORCE_FORBIDDEN_STAGE13");
    int stage = stop_env ? atoi(stop_env) : 0;
    int hold_ms = hold_env ? atoi(hold_env) : 300;

    signal(SIGTERM, on_term);
    signal(SIGINT, on_term);

    if (stage < 6 || stage > 12 || stage == 11) {
        fputs("RESEARCH_STOP_AFTER_STAGE=INVALID\n", stderr);
        return 64;
    }

    printf("RESEARCH_STOP_AFTER_STAGE=%d\n", stage);
    fflush(stdout);
    emit_until_stage(stage);
    puts("RESEARCH_HOLD_ENTERED=true");
    puts("SELF_ACTIVATION_SENT=false");
    puts("RTPC_OPENED=false");
    puts("RTP_STARTED=false");
    fflush(stdout);

    if (forbidden && strcmp(forbidden, "1") == 0) {
        fputs("FORBIDDEN_STAGE_CROSSING=ENTRANCE_SIGNALING_ARMED\n", stderr);
        return 70;
    }

    for (int elapsed = 0; elapsed < hold_ms && !term_seen; elapsed += 20)
        usleep(20000);

    puts("RESEARCH_TEARDOWN_BEGIN=true");
    puts(term_seen ? "RESEARCH_TEARDOWN_REASON=sigterm" : "RESEARCH_TEARDOWN_REASON=timeout");
    puts("RESEARCH_TEMP_SECRET_REMOVED=true");
    puts("RESEARCH_CHILD_PROCESSES_LEFT=0");
    puts("RESEARCH_SOCKETS_CLOSED=true");
    puts("RESEARCH_TEARDOWN_DONE=true");
    fflush(stdout);
    return 0;
}
