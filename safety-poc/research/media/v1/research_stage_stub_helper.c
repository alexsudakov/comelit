#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <unistd.h>

static volatile sig_atomic_t term_seen = 0;

static void on_term(int signum) {
    (void)signum;
    term_seen = 1;
}

static void write_offer_file(void) {
    const char *path = getenv("RESEARCH_OFFER_FILE");
    if (!path || !*path) return;
    FILE *handle = fopen(path, "w");
    if (!handle) return;
    fputs("v=0\r\n"
          "o=- 1 1 IN IP4 127.0.0.1\r\n"
          "s=Comelit research local offer\r\n"
          "t=0 0\r\n"
          "a=ice-ufrag:localufrag\r\n"
          "a=ice-pwd:localpassword\r\n"
          "a=candidate:1 1 UDP 2130706431 127.0.0.1 5000 typ host\r\n",
          handle);
    fclose(handle);
}

static void teardown(const char *reason) {
    puts("RESEARCH_TEARDOWN_BEGIN=true");
    printf("RESEARCH_STAGE_6_PAUSE_REASON=%s\n", reason);
    printf("RESEARCH_TEARDOWN_REASON=%s\n", reason);
    puts("RESEARCH_TEMP_SECRET_REMOVED=true");
    puts("RESEARCH_CHILD_PROCESSES_LEFT=0");
    puts("RESEARCH_SOCKETS_CLOSED=true");
    puts("RESEARCH_TEARDOWN_DONE=true");
    fflush(stdout);
}

static int wait_stage6_gate(int hold_ms) {
    const char *control_path = getenv("RESEARCH_STAGE6_CONTROL_PATH");
    int fd;
    int elapsed = 0;
    char buf[64];

    write_offer_file();
    puts("RESEARCH_STAGE_6_LOCAL_OFFER_READY");
    puts("RESEARCH_STAGE_6_PAUSE_ENTERED=true");
    fflush(stdout);

    if (!control_path || !*control_path) {
        teardown("CHANNEL_LOST");
        return 72;
    }

    fd = open(control_path, O_RDONLY | O_NONBLOCK);
    if (fd < 0) {
        teardown("CHANNEL_LOST");
        return 72;
    }

    while (elapsed < hold_ms && !term_seen) {
        fd_set rfds;
        struct timeval tv;
        int selected;

        FD_ZERO(&rfds);
        FD_SET(fd, &rfds);
        tv.tv_sec = 0;
        tv.tv_usec = 20000;
        selected = select(fd + 1, &rfds, NULL, NULL, &tv);
        if (selected > 0 && FD_ISSET(fd, &rfds)) {
            ssize_t got = read(fd, buf, sizeof(buf) - 1);
            if (got <= 0) {
                close(fd);
                teardown("CHANNEL_LOST");
                return 72;
            }
            buf[got] = '\0';
            if (strstr(buf, "CONTINUE")) {
                close(fd);
                puts("RESEARCH_STAGE_6_PAUSE_REASON=CONTINUE");
                fflush(stdout);
                return 0;
            }
            if (strstr(buf, "ABORT")) {
                close(fd);
                teardown("ABORT");
                return 0;
            }
            close(fd);
            teardown("CHANNEL_LOST");
            return 72;
        }
        elapsed += 20;
    }

    close(fd);
    if (term_seen) {
        teardown("SIGTERM");
        return 0;
    }
    teardown("TIMEOUT");
    return 70;
}

static int emit_after_stage6(int stage) {
    puts("RESEARCH_STAGE_6_LOCAL_OFFER_READY");
    fflush(stdout);
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
    if (stage == 6 || stage == 7) {
        int gate_rc = wait_stage6_gate(hold_ms);
        if (gate_rc != 0 || stage == 6) return gate_rc;
    } else {
        emit_after_stage6(stage);
    }

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

    teardown(term_seen ? "SIGTERM" : "TIMEOUT");
    return 0;
}
