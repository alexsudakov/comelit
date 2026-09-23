/*
 * Offline whole-translation-unit compile gate: minimal stand-in for
 * libnice's nice/pseudotcp.h. See ../glib.h for rationale; not linked or
 * executed, only used for `cc -fsyntax-only` declaration-order checking.
 */
#ifndef COMELIT_STUB_NICE_PSEUDOTCP_H
#define COMELIT_STUB_NICE_PSEUDOTCP_H

#include "../glib.h"

typedef struct PseudoTcpSocket PseudoTcpSocket;

typedef int PseudoTcpWriteResult;
#define WR_SUCCESS 0
#define WR_FAIL 1
#define WR_TOO_LARGE 2

typedef void (*PseudoTcpOpened)(PseudoTcpSocket *tcp, gpointer data);
typedef void (*PseudoTcpReadable)(PseudoTcpSocket *tcp, gpointer data);
typedef void (*PseudoTcpWritable)(PseudoTcpSocket *tcp, gpointer data);
typedef void (*PseudoTcpClosed)(PseudoTcpSocket *tcp, guint32 error, gpointer data);
typedef PseudoTcpWriteResult (*PseudoTcpWritePacket)(
    PseudoTcpSocket *tcp, const gchar *buffer, guint32 len, gpointer data);

typedef struct _PseudoTcpCallbacks {
    gpointer user_data;
    PseudoTcpOpened PseudoTcpOpened;
    PseudoTcpReadable PseudoTcpReadable;
    PseudoTcpWritable PseudoTcpWritable;
    PseudoTcpClosed PseudoTcpClosed;
    PseudoTcpWritePacket WritePacket;
} PseudoTcpCallbacks;

gpointer pseudo_tcp_socket_new();
gboolean pseudo_tcp_socket_connect();
gboolean pseudo_tcp_socket_close();
gboolean pseudo_tcp_socket_is_closed();
gint pseudo_tcp_socket_get_error();
gint pseudo_tcp_socket_send();
gint pseudo_tcp_socket_recv();
void pseudo_tcp_socket_notify_mtu();
void pseudo_tcp_socket_notify_clock();
gboolean pseudo_tcp_socket_get_next_clock();
gboolean pseudo_tcp_socket_notify_packet();

#endif /* COMELIT_STUB_NICE_PSEUDOTCP_H */
