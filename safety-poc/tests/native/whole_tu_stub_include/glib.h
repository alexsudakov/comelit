/*
 * Offline whole-translation-unit compile gate: minimal stand-in for glib.h.
 *
 * This is NOT a functional glib. It exists only so `cc -fsyntax-only` can
 * parse and type-check the *whole* generated comelit-v4 source (declaration
 * order, undeclared identifiers, implicit-declaration, static/non-static
 * conflicts) without the real Alpine/musl glib-2.0 dev headers, which are
 * not available offline in this sandbox. Function bodies are never linked
 * or executed by this gate. Pointer-returning glib calls are declared to
 * return `gpointer` (== void*) deliberately: C allows implicit conversion
 * between void* and any object pointer type, so this avoids having to
 * reproduce every real glib prototype exactly while still catching the
 * declaration-order class of defect this gate targets.
 */
#ifndef COMELIT_STUB_GLIB_H
#define COMELIT_STUB_GLIB_H

#include <stddef.h>
#include <stdint.h>

typedef int gboolean;
typedef int gint;
typedef unsigned int guint;
typedef char gchar;
typedef unsigned char guchar;
typedef long long gint64;
typedef unsigned long long guint64;
typedef uint8_t guint8;
typedef uint16_t guint16;
typedef uint32_t guint32;
typedef void *gpointer;
typedef const void *gconstpointer;
typedef size_t gsize;
typedef ptrdiff_t gssize;
typedef float gfloat;
typedef double gdouble;
typedef gint64 goffset;

#ifndef TRUE
#define TRUE 1
#endif
#ifndef FALSE
#define FALSE 0
#endif

#define G_USEC_PER_SEC 1000000
#define G_MAXUINT ((guint)-1)
#define G_GUINT64_FORMAT "llu"
#define G_CHECKSUM_SHA256 0
#define G_FILE_TEST_EXISTS 1
#define G_SOURCE_CONTINUE TRUE
#define G_SOURCE_REMOVE FALSE
#define G_OBJECT(x) ((gpointer)(x))
#define G_CALLBACK(f) ((GCallback)(f))

#ifndef MAX
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#endif
#ifndef MIN
#define MIN(a, b) ((a) < (b) ? (a) : (b))
#endif

typedef void (*GCallback)(void);
typedef void (*GDestroyNotify)(gpointer data);

typedef struct GMainLoop GMainLoop;
typedef struct GMainContext GMainContext;
typedef struct GChecksum GChecksum;
typedef struct _GError GError;

typedef struct _GSList GSList;
struct _GSList {
    gpointer data;
    GSList *next;
};

/* Main loop */
gpointer g_main_loop_new();
void g_main_loop_run();
void g_main_loop_quit();
void g_main_loop_unref();
gpointer g_main_loop_get_context();

/* Time */
gint64 g_get_monotonic_time();
gint64 g_get_real_time();

/* Event sources */
guint g_timeout_add();
guint g_timeout_add_seconds();

/* GObject-ish */
void g_object_get();
void g_object_set();
void g_object_unref();
gint64 g_signal_connect();

/* Singly-linked list */
gpointer g_slist_prepend();
gpointer g_slist_reverse();
void g_slist_free_full();

/* Strings */
gboolean g_str_has_prefix();
gint g_strcmp0();
gpointer g_strdup();
gpointer g_strdup_printf();
void g_strfreev();
gsize g_strlcpy();
gpointer g_strndup();
gpointer g_strsplit();
gpointer g_strsplit_set();
gpointer g_strstr_len();
gpointer g_strstrip();
gint g_snprintf();

gboolean g_ascii_isprint();
gboolean g_ascii_isspace();
gboolean g_ascii_isxdigit();
gpointer g_ascii_strdown();
gint64 g_ascii_strtoll();

/* Checksums */
gpointer g_checksum_new();
void g_checksum_update();
gpointer g_checksum_get_string();
void g_checksum_free();
gpointer g_compute_checksum_for_data();

/* Errors, files, memory, misc */
void g_error_free();
gboolean g_file_get_contents();
gboolean g_file_set_contents();
gboolean g_file_test();
void g_free();
guint32 g_random_int();

#endif /* COMELIT_STUB_GLIB_H */
