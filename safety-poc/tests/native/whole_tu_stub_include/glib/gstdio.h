/* Stub for the whole-TU offline compile gate. See ../glib.h for rationale. */
#ifndef COMELIT_STUB_GLIB_GSTDIO_H
#define COMELIT_STUB_GLIB_GSTDIO_H

#include "../glib.h"
#include <sys/stat.h>

typedef struct stat GStatBuf;

gint g_mkdir_with_parents();
gint g_stat();

#endif /* COMELIT_STUB_GLIB_GSTDIO_H */
