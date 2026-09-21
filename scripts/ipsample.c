/* LD_PRELOAD instruction-pointer sampler.
 *
 * SPEC.ja.md 10 wants post-hoc attribution from `perf` or
 * `valgrind --tool=callgrind`. Neither is installed on this machine
 * (results.md "Day 0 (toy)" section 3 records that `perf` is missing;
 * valgrind is missing too), and `gdb -p` cannot attach from a non-ancestor
 * because /proc/sys/kernel/yama/ptrace_scope is 1.
 *
 * This is the smallest thing that answers the one question the oxipng target
 * makes urgent: what share of the wall time runs in code that rustc compiled,
 * versus code that a C compiler compiled? `-Cprofile-generate` instruments
 * Rust only, so a profdata-based share (scripts/profdata_hotness.py) reports
 * 100% Rust for a program whose hot loop is in a vendored C library. A
 * sampled instruction pointer does not have that blind spot.
 *
 * Mechanism: ITIMER_PROF (CPU time, not wall time, so an idle wait does not
 * produce samples) fires SIGPROF; the handler records RIP out of the
 * ucontext. At exit the samples are written as one hex address per line,
 * already rebased to file offsets of the main executable, so that `nm` output
 * resolves them directly. Addresses outside the main executable's mapping are
 * written with their mapping name so shared libraries can be told apart.
 *
 * Build and use:
 *   cc -O2 -fPIC -shared -o /tmp/ipsample.so scripts/ipsample.c
 *   IPSAMPLE_OUT=/tmp/s.txt LD_PRELOAD=/tmp/ipsample.so ./prog args...
 *   scripts/ipsample.py --binary ./prog /tmp/s.txt
 *
 * Environment:
 *   IPSAMPLE_OUT    output path (default: ipsample.txt in the cwd)
 *   IPSAMPLE_USEC   sampling period in microseconds (default 1000)
 */

#define _GNU_SOURCE
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <ucontext.h>
#include <unistd.h>

#define MAX_SAMPLES (1 << 22)

static unsigned long samples[MAX_SAMPLES];
static volatile unsigned long n_samples;
static unsigned long exe_lo, exe_hi;
static char out_path[4096];

static void on_prof(int sig, siginfo_t *si, void *uc) {
    (void)sig;
    (void)si;
    unsigned long n = n_samples;
    if (n >= MAX_SAMPLES) return;
    ucontext_t *c = (ucontext_t *)uc;
    samples[n] = (unsigned long)c->uc_mcontext.gregs[REG_RIP];
    n_samples = n + 1;
}

/* Find the address range of the main executable's mappings, so that a sample
 * can be rebased to a file offset (the binary is a PIE). */
static void find_exe_range(void) {
    char exe[4096];
    ssize_t len = readlink("/proc/self/exe", exe, sizeof(exe) - 1);
    if (len <= 0) return;
    exe[len] = 0;

    FILE *f = fopen("/proc/self/maps", "r");
    if (!f) return;
    char line[8192];
    while (fgets(line, sizeof(line), f)) {
        unsigned long lo, hi;
        char perms[8], path[4096];
        path[0] = 0;
        if (sscanf(line, "%lx-%lx %7s %*s %*s %*s %4095s",
                   &lo, &hi, perms, path) < 4)
            continue;
        if (strcmp(path, exe) != 0) continue;
        if (exe_lo == 0 || lo < exe_lo) exe_lo = lo;
        if (hi > exe_hi) exe_hi = hi;
    }
    fclose(f);
}

/* Write "OFFSET" for a sample inside the main executable and "!OTHER" for one
 * outside it. Resolution of an offset to a symbol is scripts/ipsample.py's
 * job; doing it here would mean parsing ELF in a signal-safe context. */
static void dump(void) {
    static int done;
    if (done) return;
    done = 1;

    struct itimerval off;
    memset(&off, 0, sizeof(off));
    setitimer(ITIMER_PROF, &off, NULL);

    FILE *f = fopen(out_path, "w");
    if (!f) return;
    fprintf(f, "# exe_range %lx-%lx samples %lu\n", exe_lo, exe_hi, n_samples);
    for (unsigned long i = 0; i < n_samples; i++) {
        unsigned long ip = samples[i];
        if (ip >= exe_lo && ip < exe_hi)
            fprintf(f, "%lx\n", ip - exe_lo);
        else
            fprintf(f, "!%lx\n", ip);
    }
    fclose(f);
}

__attribute__((constructor)) static void ipsample_start(void) {
    const char *p = getenv("IPSAMPLE_OUT");
    snprintf(out_path, sizeof(out_path), "%s", p ? p : "ipsample.txt");

    long usec = 1000;
    const char *u = getenv("IPSAMPLE_USEC");
    if (u) {
        long v = atol(u);
        if (v > 0) usec = v;
    }

    find_exe_range();

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = on_prof;
    sa.sa_flags = SA_SIGINFO | SA_RESTART;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGPROF, &sa, NULL);

    struct itimerval it;
    it.it_interval.tv_sec = usec / 1000000;
    it.it_interval.tv_usec = usec % 1000000;
    it.it_value = it.it_interval;
    setitimer(ITIMER_PROF, &it, NULL);

    atexit(dump);
}

__attribute__((destructor)) static void ipsample_end(void) { dump(); }
