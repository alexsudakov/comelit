/*
 * Offline whole-translation-unit compile gate: minimal stand-in for
 * libnice's nice/agent.h. See ../glib.h for rationale; not linked or
 * executed, only used for `cc -fsyntax-only` declaration-order checking.
 */
#ifndef COMELIT_STUB_NICE_AGENT_H
#define COMELIT_STUB_NICE_AGENT_H

#include "../glib.h"

typedef struct _NiceAgent NiceAgent;
typedef gint NiceComponentState;

typedef struct _NiceCandidate {
    gint type;
    gint transport;
    guint component_id;
} NiceCandidate;

#define NICE_COMPATIBILITY_RFC5245 0
#define NICE_AGENT_CREATE 0

#define NICE_CANDIDATE_TRANSPORT_UDP 0

#define NICE_CANDIDATE_TYPE_HOST 0
#define NICE_CANDIDATE_TYPE_SERVER_REFLEXIVE 1
#define NICE_CANDIDATE_TYPE_PEER_REFLEXIVE 2
#define NICE_CANDIDATE_TYPE_RELAYED 3

#define NICE_COMPONENT_STATE_DISCONNECTED 0
#define NICE_COMPONENT_STATE_GATHERING 1
#define NICE_COMPONENT_STATE_CONNECTING 2
#define NICE_COMPONENT_STATE_CONNECTED 3
#define NICE_COMPONENT_STATE_READY 4
#define NICE_COMPONENT_STATE_FAILED 5

gpointer nice_agent_new();
guint nice_agent_add_stream();
gboolean nice_agent_attach_recv();
gboolean nice_agent_gather_candidates();
gpointer nice_agent_generate_local_sdp();
gpointer nice_agent_get_local_candidates();
gboolean nice_agent_get_local_credentials();
gboolean nice_agent_get_selected_pair();
gpointer nice_agent_parse_remote_candidate_sdp();
gint nice_agent_send();
gboolean nice_agent_set_remote_candidates();
gboolean nice_agent_set_remote_credentials();
void nice_agent_set_stream_name();
void nice_candidate_free();

#endif /* COMELIT_STUB_NICE_AGENT_H */
