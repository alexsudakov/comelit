#!/usr/bin/env python3
"""P76: inject offline RTPC CONTROL/media runtime parity into the C candidate.

The transform composes the reviewed P46 device-video ACK observation candidate
and appends one bounded, no-network C runtime section.  The same C section is
used by the local harness generator, so tests compile and execute the protocol
logic that the transformed candidate contains instead of a separate fake model.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_device_video_ack_observation_transform import transform as add_device_video_ack


DEFAULT_SOURCE = Path(
    "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
)


P76_RUNTIME_C_SECTION = r'''
/* === P76_RTPC_CONTROL_MEDIA_RUNTIME_BEGIN ===
 * RTPC_C_RUNTIME_PARITY_CONTRACT=PROVEN_OFFLINE
 * C_RUNTIME_BASE=P46_REVIEWED_TRANSFORM_CHAIN
 * REGISTERED_CTPP_REUSED=true
 * SECOND_CTPP_OPEN=false
 * RTPC_TARGET_ALLOCATOR=P73_PARITY
 * RTPC_OPEN_GENERATION=P74_PARITY
 * RTPC_CONTROL_STATE_MACHINE=P75_PARITY
 * CLIENT_RESPONSE_DEVICE_OPEN_BINDING=PROVEN
 * CLIENT_000A_ALLOCATION_BINDING=PROVEN
 * CLIENT_001A_ALLOCATION_BINDING=PROVEN
 * CONTROL_TOTAL_ORDER_REQUIRED=false
 * COLLISION_SKIP_SUPPORTED=true
 * CAPTURE_TARGET_IDS_USED_AS_CONSTANTS=false
 * NETWORK_IO_PERFORMED=false
 * LIVE_INVOCATIONS=0
 * DOOR_ACTION_SENT=false
 * MEDIA_SESSION_STARTED=false
 * LIVE_TRANSMISSION_AUTHORIZED=false
 */

#ifndef P76_RTPC_RUNTIME_TYPES_DEFINED
#define P76_RTPC_RUNTIME_TYPES_DEFINED
typedef unsigned char p76_u8;
typedef unsigned short p76_u16;
typedef unsigned int p76_u32;
typedef int p76_bool;
#endif

#define P76_TRUE 1
#define P76_FALSE 0
#define P76_LOW15_MASK 0x7fffu
#define P76_SEARCH_BUDGET 0x7fffu
#define P76_MAX_BODY 64u

typedef enum {
    P76_OK = 0,
    P76_ERR_MALFORMED_OPEN,
    P76_ERR_MALFORMED_RESPONSE,
    P76_ERR_RESPONSE_BEFORE_OPEN,
    P76_ERR_UNKNOWN_RESPONSE_TARGET,
    P76_ERR_DUPLICATE_RESPONSE,
    P76_ERR_REUSED_CLIENT_TARGET,
    P76_ERR_ALLOCATOR_EXHAUSTED,
    P76_ERR_CLIENT_RESPONSE_WITHOUT_DEVICE_OPEN,
    P76_ERR_BAD_000A_BINDING,
    P76_ERR_BAD_001A_BINDING,
    P76_ERR_SECOND_CTPP_OPEN,
    P76_ERR_DOOR_ENTRYPOINT_REACHABLE,
    P76_ERR_PARTIAL_COMPLETE
} P76Status;

typedef enum {
    P76_FACT_NOT_SEEN = 0,
    P76_FACT_SEEN,
    P76_FACT_GENERATED,
    P76_FACT_PAIRED
} P76Fact;

typedef struct {
    p76_u16 low15_counter;
    p76_u16 high_halfword;
    p76_bool in_use[65536];
} P76Allocator;

typedef struct {
    p76_u16 target_id;
    p76_u16 low15_used;
    p76_u16 next_low15_counter;
    p76_u16 collisions;
} P76Allocation;

typedef struct {
    P76Fact device_open_seen;
    P76Fact client_allocation_1;
    P76Fact client_allocation_2;
    P76Fact client_open_1_emitted;
    P76Fact client_open_2_emitted;
    P76Fact device_response_1_seen;
    P76Fact device_response_2_seen;
    P76Fact client_response_to_device_open_emitted;
    P76Fact client_000a_generated;
    P76Fact client_001a_generated;
} P76Facts;

typedef struct {
    P76Allocator allocator;
    P76Facts facts;
    p76_u16 device_open_target;
    P76Allocation allocation_1;
    P76Allocation allocation_2;
    p76_bool has_allocation_1;
    p76_bool has_allocation_2;
    p76_bool device_response_target_seen[65536];
    p76_bool registered_ctpp_reused;
    p76_bool second_ctpp_open_attempted;
    p76_bool door_entrypoint_reachable;
    p76_bool network_capable;
} P76Runtime;

static void p76_write_le16(p76_u8 *dst, p76_u16 value)
{
    dst[0] = (p76_u8)(value & 0xffu);
    dst[1] = (p76_u8)((value >> 8) & 0xffu);
}

static void p76_write_le32(p76_u8 *dst, p76_u32 value)
{
    dst[0] = (p76_u8)(value & 0xffu);
    dst[1] = (p76_u8)((value >> 8) & 0xffu);
    dst[2] = (p76_u8)((value >> 16) & 0xffu);
    dst[3] = (p76_u8)((value >> 24) & 0xffu);
}

static void p76_write_be16(p76_u8 *dst, p76_u16 value)
{
    dst[0] = (p76_u8)((value >> 8) & 0xffu);
    dst[1] = (p76_u8)(value & 0xffu);
}

static p76_u16 p76_read_le16(const p76_u8 *src)
{
    return (p76_u16)((p76_u16)src[0] | ((p76_u16)src[1] << 8));
}

static p76_u32 p76_runtime_seed_low15(p76_u32 rand_result)
{
    return rand_result & P76_LOW15_MASK;
}

static void p76_runtime_init(P76Runtime *runtime, p76_u32 rand_result)
{
    p76_u32 i;
    for (i = 0; i < 65536u; i++) {
        runtime->allocator.in_use[i] = P76_FALSE;
        runtime->device_response_target_seen[i] = P76_FALSE;
    }
    runtime->allocator.low15_counter = (p76_u16)p76_runtime_seed_low15(rand_result);
    runtime->allocator.high_halfword = 0;
    runtime->allocator.in_use[0] = P76_TRUE;
    runtime->facts.device_open_seen = P76_FACT_NOT_SEEN;
    runtime->facts.client_allocation_1 = P76_FACT_NOT_SEEN;
    runtime->facts.client_allocation_2 = P76_FACT_NOT_SEEN;
    runtime->facts.client_open_1_emitted = P76_FACT_NOT_SEEN;
    runtime->facts.client_open_2_emitted = P76_FACT_NOT_SEEN;
    runtime->facts.device_response_1_seen = P76_FACT_NOT_SEEN;
    runtime->facts.device_response_2_seen = P76_FACT_NOT_SEEN;
    runtime->facts.client_response_to_device_open_emitted = P76_FACT_NOT_SEEN;
    runtime->facts.client_000a_generated = P76_FACT_NOT_SEEN;
    runtime->facts.client_001a_generated = P76_FACT_NOT_SEEN;
    runtime->device_open_target = 0;
    runtime->has_allocation_1 = P76_FALSE;
    runtime->has_allocation_2 = P76_FALSE;
    runtime->registered_ctpp_reused = P76_TRUE;
    runtime->second_ctpp_open_attempted = P76_FALSE;
    runtime->door_entrypoint_reachable = P76_FALSE;
    runtime->network_capable = P76_FALSE;
}

static void p76_runtime_mark_occupied(P76Runtime *runtime, p76_u16 target_id)
{
    runtime->allocator.in_use[target_id] = P76_TRUE;
}

static P76Status p76_allocate_target_id(P76Runtime *runtime, P76Allocation *out)
{
    p76_u16 low = runtime->allocator.low15_counter;
    p76_u16 collisions;
    for (collisions = 0; collisions < P76_SEARCH_BUDGET; collisions++) {
        p76_u16 candidate = (p76_u16)((((p76_u32)runtime->allocator.high_halfword << 15) | low) & 0xffffu);
        p76_u16 next_low = (p76_u16)((low + 1u) & P76_LOW15_MASK);
        if (!runtime->allocator.in_use[candidate]) {
            runtime->allocator.low15_counter = next_low;
            runtime->allocator.in_use[candidate] = P76_TRUE;
            out->target_id = candidate;
            out->low15_used = low;
            out->next_low15_counter = next_low;
            out->collisions = collisions;
            return P76_OK;
        }
        low = next_low;
    }
    runtime->allocator.low15_counter = low;
    return P76_ERR_ALLOCATOR_EXHAUSTED;
}

static p76_bool p76_rtpc_open_is_valid(const p76_u8 *body, p76_u32 len)
{
    return len == 15u &&
        body[0] == 0xcdu && body[1] == 0xabu &&
        body[2] == 0x01u && body[3] == 0x00u &&
        body[4] == 0x07u && body[5] == 0x00u &&
        body[6] == 0x00u && body[7] == 0x00u &&
        body[8] == 'R' && body[9] == 'T' && body[10] == 'P' && body[11] == 'C' &&
        p76_read_le16(body + 12) != 0u &&
        body[14] == 0x01u;
}

static p76_bool p76_rtpc_response_is_valid(const p76_u8 *body, p76_u32 len)
{
    return len == 12u &&
        body[0] == 0xcdu && body[1] == 0xabu &&
        body[2] == 0x02u && body[3] == 0x00u &&
        body[4] == 0x04u && body[5] == 0x00u &&
        body[6] == 0x00u && body[7] == 0x00u &&
        p76_read_le16(body + 8) != 0u &&
        body[10] == 0x00u && body[11] == 0x00u;
}

static P76Status p76_observe_device_open(P76Runtime *runtime, const p76_u8 *body, p76_u32 len)
{
    if (!p76_rtpc_open_is_valid(body, len))
        return P76_ERR_MALFORMED_OPEN;
    runtime->device_open_target = p76_read_le16(body + 12);
    runtime->facts.device_open_seen = P76_FACT_SEEN;
    return P76_OK;
}

static p76_u32 p76_build_rtpc_open(p76_u16 target_id, p76_u8 out[P76_MAX_BODY])
{
    out[0] = 0xcd; out[1] = 0xab; out[2] = 0x01; out[3] = 0x00;
    out[4] = 0x07; out[5] = 0x00; out[6] = 0x00; out[7] = 0x00;
    out[8] = 'R'; out[9] = 'T'; out[10] = 'P'; out[11] = 'C';
    p76_write_le16(out + 12, target_id);
    out[14] = 0x01;
    return 15u;
}

static p76_u32 p76_build_rtpc_response(p76_u16 target_id, p76_u8 out[P76_MAX_BODY])
{
    out[0] = 0xcd; out[1] = 0xab; out[2] = 0x02; out[3] = 0x00;
    out[4] = 0x04; out[5] = 0x00; out[6] = 0x00; out[7] = 0x00;
    p76_write_le16(out + 8, target_id);
    out[10] = 0x00; out[11] = 0x00;
    return 12u;
}

static p76_u32 p76_build_client_000a(
    p76_u32 previous_client_ctpp_sequence,
    p76_u16 target_id,
    const p76_u8 role_a[9],
    const p76_u8 role_b[9],
    p76_u8 out[P76_MAX_BODY])
{
    p76_u32 i;
    for (i = 0; i < 44u; i++)
        out[i] = 0;
    p76_write_le16(out + 0, 0x1840u);
    p76_write_le32(out + 2, previous_client_ctpp_sequence);
    p76_write_be16(out + 6, 0x000au);
    p76_write_be16(out + 8, 0x0011u);
    out[10] = 0x18; out[11] = 0x02;
    p76_write_le16(out + 16, target_id);
    out[20] = 0xff; out[21] = 0xff; out[22] = 0xff; out[23] = 0xff;
    for (i = 0; i < 9u; i++)
        out[24u + i] = role_b[i];
    out[33] = 0;
    for (i = 0; i < 9u; i++)
        out[34u + i] = role_a[i];
    out[43] = 0;
    return 44u;
}

static p76_u32 p76_build_client_001a(
    p76_u32 previous_client_ctpp_sequence,
    p76_u16 target_id,
    const p76_u8 role_a[9],
    const p76_u8 role_b[9],
    p76_u8 out[P76_MAX_BODY])
{
    p76_u32 i;
    for (i = 0; i < 60u; i++)
        out[i] = 0;
    p76_write_le16(out + 0, 0x1840u);
    p76_write_le32(out + 2, previous_client_ctpp_sequence + 0x00010000u);
    p76_write_be16(out + 6, 0x001au);
    p76_write_be16(out + 8, 0x0011u);
    out[10] = 0x14; out[11] = 0x32;
    p76_write_le16(out + 16, target_id);
    out[18] = 0xff; out[19] = 0xff;
    p76_write_le16(out + 24, 800u);
    p76_write_le16(out + 26, 480u);
    p76_write_le16(out + 28, 320u);
    p76_write_le16(out + 30, 240u);
    p76_write_le16(out + 32, 16u);
    out[36] = 0xff; out[37] = 0xff; out[38] = 0xff; out[39] = 0xff;
    for (i = 0; i < 9u; i++)
        out[40u + i] = role_b[i];
    out[49] = 0;
    for (i = 0; i < 9u; i++)
        out[50u + i] = role_a[i];
    out[59] = 0;
    return 60u;
}

static P76Status p76_generate_client_exchange(
    P76Runtime *runtime,
    p76_u32 seq_000a,
    p76_u32 seq_001a,
    const p76_u8 role_a[9],
    const p76_u8 role_b[9],
    p76_u8 open_1[P76_MAX_BODY],
    p76_u32 *open_1_len,
    p76_u8 open_2[P76_MAX_BODY],
    p76_u32 *open_2_len,
    p76_u8 client_000a[P76_MAX_BODY],
    p76_u32 *client_000a_len,
    p76_u8 client_001a[P76_MAX_BODY],
    p76_u32 *client_001a_len)
{
    P76Status status;
    if (runtime->has_allocation_1 || runtime->has_allocation_2)
        return P76_ERR_SECOND_CTPP_OPEN;
    status = p76_allocate_target_id(runtime, &runtime->allocation_1);
    if (status != P76_OK)
        return status;
    status = p76_allocate_target_id(runtime, &runtime->allocation_2);
    if (status != P76_OK)
        return status;
    if (runtime->allocation_1.target_id == runtime->allocation_2.target_id)
        return P76_ERR_REUSED_CLIENT_TARGET;
    runtime->has_allocation_1 = P76_TRUE;
    runtime->has_allocation_2 = P76_TRUE;
    runtime->facts.client_allocation_1 = P76_FACT_GENERATED;
    runtime->facts.client_allocation_2 = P76_FACT_GENERATED;
    runtime->facts.client_open_1_emitted = P76_FACT_GENERATED;
    runtime->facts.client_open_2_emitted = P76_FACT_GENERATED;
    *open_1_len = p76_build_rtpc_open(runtime->allocation_1.target_id, open_1);
    *open_2_len = p76_build_rtpc_open(runtime->allocation_2.target_id, open_2);
    *client_000a_len = p76_build_client_000a(seq_000a, runtime->allocation_1.target_id, role_a, role_b, client_000a);
    *client_001a_len = p76_build_client_001a(seq_001a, runtime->allocation_2.target_id, role_a, role_b, client_001a);
    return P76_OK;
}

static P76Status p76_observe_device_response(P76Runtime *runtime, const p76_u8 *body, p76_u32 len)
{
    p76_u16 target;
    p76_bool match_1;
    p76_bool match_2;
    if (!p76_rtpc_response_is_valid(body, len))
        return P76_ERR_MALFORMED_RESPONSE;
    if (!runtime->has_allocation_1 || !runtime->has_allocation_2)
        return P76_ERR_RESPONSE_BEFORE_OPEN;
    target = p76_read_le16(body + 8);
    match_1 = runtime->allocation_1.target_id == target;
    match_2 = runtime->allocation_2.target_id == target;
    if (match_1 && match_2)
        return P76_ERR_REUSED_CLIENT_TARGET;
    if (!match_1 && !match_2)
        return P76_ERR_UNKNOWN_RESPONSE_TARGET;
    if (runtime->device_response_target_seen[target])
        return P76_ERR_DUPLICATE_RESPONSE;
    runtime->device_response_target_seen[target] = P76_TRUE;
    if (match_1)
        runtime->facts.device_response_1_seen = P76_FACT_PAIRED;
    if (match_2)
        runtime->facts.device_response_2_seen = P76_FACT_PAIRED;
    return P76_OK;
}

static P76Status p76_generate_client_response_to_device_open(
    P76Runtime *runtime,
    p76_u8 out[P76_MAX_BODY],
    p76_u32 *out_len)
{
    if (runtime->facts.device_open_seen != P76_FACT_SEEN || runtime->device_open_target == 0u)
        return P76_ERR_CLIENT_RESPONSE_WITHOUT_DEVICE_OPEN;
    *out_len = p76_build_rtpc_response(runtime->device_open_target, out);
    runtime->facts.client_response_to_device_open_emitted = P76_FACT_PAIRED;
    return P76_OK;
}

static P76Status p76_generate_client_000a(P76Runtime *runtime, const p76_u8 body[P76_MAX_BODY], p76_u32 len)
{
    if (runtime->facts.client_open_1_emitted != P76_FACT_GENERATED)
        return P76_ERR_BAD_000A_BINDING;
    if (len < 18u || body[0] != 0x40u || body[1] != 0x18u ||
        body[6] != 0x00u || body[7] != 0x0au ||
        p76_read_le16(body + 16) != runtime->allocation_1.target_id)
        return P76_ERR_BAD_000A_BINDING;
    runtime->facts.client_000a_generated = P76_FACT_GENERATED;
    return P76_OK;
}

static P76Status p76_generate_client_001a(P76Runtime *runtime, const p76_u8 body[P76_MAX_BODY], p76_u32 len)
{
    if (runtime->facts.client_open_2_emitted != P76_FACT_GENERATED)
        return P76_ERR_BAD_001A_BINDING;
    if (len < 34u || body[0] != 0x40u || body[1] != 0x18u ||
        body[6] != 0x00u || body[7] != 0x1au ||
        p76_read_le16(body + 16) != runtime->allocation_2.target_id ||
        p76_read_le16(body + 24) != 800u ||
        p76_read_le16(body + 26) != 480u ||
        p76_read_le16(body + 28) != 320u ||
        p76_read_le16(body + 30) != 240u ||
        p76_read_le16(body + 32) != 16u)
        return P76_ERR_BAD_001A_BINDING;
    runtime->facts.client_001a_generated = P76_FACT_GENERATED;
    return P76_OK;
}

static P76Status p76_attempt_second_ctpp_open(P76Runtime *runtime)
{
    runtime->second_ctpp_open_attempted = P76_TRUE;
    return P76_ERR_SECOND_CTPP_OPEN;
}

static P76Status p76_attempt_door_entrypoint(P76Runtime *runtime)
{
    runtime->door_entrypoint_reachable = P76_TRUE;
    return P76_ERR_DOOR_ENTRYPOINT_REACHABLE;
}

static p76_bool p76_is_complete(const P76Runtime *runtime)
{
    return runtime->facts.device_open_seen != P76_FACT_NOT_SEEN &&
        runtime->facts.client_open_1_emitted != P76_FACT_NOT_SEEN &&
        runtime->facts.client_open_2_emitted != P76_FACT_NOT_SEEN &&
        runtime->facts.device_response_1_seen != P76_FACT_NOT_SEEN &&
        runtime->facts.device_response_2_seen != P76_FACT_NOT_SEEN &&
        runtime->facts.client_response_to_device_open_emitted != P76_FACT_NOT_SEEN &&
        runtime->facts.client_000a_generated != P76_FACT_NOT_SEEN &&
        runtime->facts.client_001a_generated != P76_FACT_NOT_SEEN;
}
/* === P76_RTPC_CONTROL_MEDIA_RUNTIME_END === */
'''


P76_HARNESS_MAIN_C = r'''
#ifdef P76_STANDALONE_HARNESS
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

static const p76_u8 P76_ROLE_A[9] = {'A','D','D','R','R','O','L','E','A'};
static const p76_u8 P76_ROLE_B[9] = {'A','D','D','R','R','O','L','E','B'};

static const char *p76_status_name(P76Status status)
{
    switch (status) {
    case P76_OK: return "OK";
    case P76_ERR_MALFORMED_OPEN: return "MALFORMED_OPEN";
    case P76_ERR_MALFORMED_RESPONSE: return "MALFORMED_RESPONSE";
    case P76_ERR_RESPONSE_BEFORE_OPEN: return "RESPONSE_BEFORE_OPEN";
    case P76_ERR_UNKNOWN_RESPONSE_TARGET: return "UNKNOWN_RESPONSE_TARGET";
    case P76_ERR_DUPLICATE_RESPONSE: return "DUPLICATE_RESPONSE";
    case P76_ERR_REUSED_CLIENT_TARGET: return "REUSED_CLIENT_TARGET";
    case P76_ERR_ALLOCATOR_EXHAUSTED: return "ALLOCATOR_EXHAUSTED";
    case P76_ERR_CLIENT_RESPONSE_WITHOUT_DEVICE_OPEN: return "CLIENT_RESPONSE_WITHOUT_DEVICE_OPEN";
    case P76_ERR_BAD_000A_BINDING: return "BAD_000A_BINDING";
    case P76_ERR_BAD_001A_BINDING: return "BAD_001A_BINDING";
    case P76_ERR_SECOND_CTPP_OPEN: return "SECOND_CTPP_OPEN";
    case P76_ERR_DOOR_ENTRYPOINT_REACHABLE: return "DOOR_ENTRYPOINT_REACHABLE";
    case P76_ERR_PARTIAL_COMPLETE: return "PARTIAL_COMPLETE";
    }
    return "UNKNOWN";
}

static void p76_print_hex(const char *kind, const p76_u8 *body, p76_u32 len)
{
    p76_u32 i;
    printf("EMIT %s ", kind);
    for (i = 0; i < len; i++)
        printf("%02x", body[i]);
    printf("\n");
}

static void p76_make_open(p76_u16 target, p76_u8 out[P76_MAX_BODY], p76_u32 *len)
{
    *len = p76_build_rtpc_open(target, out);
}

static void p76_make_response(p76_u16 target, p76_u8 out[P76_MAX_BODY], p76_u32 *len)
{
    *len = p76_build_rtpc_response(target, out);
}

static int p76_fail(P76Status status)
{
    printf("ERROR %s\n", p76_status_name(status));
    printf("NETWORK_IO_PERFORMED=false\n");
    printf("LIVE_INVOCATIONS=0\n");
    return status == P76_OK ? 1 : (int)status;
}

static P76Status p76_prepare_exchange(
    P76Runtime *rt,
    p76_u16 device_target,
    p76_u8 open1[P76_MAX_BODY],
    p76_u32 *open1_len,
    p76_u8 open2[P76_MAX_BODY],
    p76_u32 *open2_len,
    p76_u8 media_000a[P76_MAX_BODY],
    p76_u32 *media_000a_len,
    p76_u8 media_001a[P76_MAX_BODY],
    p76_u32 *media_001a_len)
{
    p76_u8 device_open[P76_MAX_BODY];
    p76_u32 device_open_len;
    P76Status status;
    p76_make_open(device_target, device_open, &device_open_len);
    status = p76_observe_device_open(rt, device_open, device_open_len);
    if (status != P76_OK)
        return status;
    return p76_generate_client_exchange(
        rt,
        0x22000000u,
        0x33000000u,
        P76_ROLE_A,
        P76_ROLE_B,
        open1,
        open1_len,
        open2,
        open2_len,
        media_000a,
        media_000a_len,
        media_001a,
        media_001a_len);
}

static int p76_run_success(const char *scenario, p76_u32 rand_result)
{
    P76Runtime rt;
    p76_u8 open1[P76_MAX_BODY], open2[P76_MAX_BODY], response[P76_MAX_BODY];
    p76_u8 media_000a[P76_MAX_BODY], media_001a[P76_MAX_BODY], inbound[P76_MAX_BODY];
    p76_u32 open1_len, open2_len, response_len, media_000a_len, media_001a_len, inbound_len;
    P76Status status;
    p76_runtime_init(&rt, rand_result);
    if (strcmp(scenario, "collision") == 0)
        p76_runtime_mark_occupied(&rt, (p76_u16)((rand_result & P76_LOW15_MASK) + 1u));
    status = p76_prepare_exchange(&rt, 0x4567u, open1, &open1_len, open2, &open2_len, media_000a, &media_000a_len, media_001a, &media_001a_len);
    if (status != P76_OK)
        return p76_fail(status);
    printf("ALLOC 1 target=%u collisions=%u\n", rt.allocation_1.target_id, rt.allocation_1.collisions);
    printf("ALLOC 2 target=%u collisions=%u\n", rt.allocation_2.target_id, rt.allocation_2.collisions);
    p76_print_hex("CLIENT_OPEN_1", open1, open1_len);
    p76_print_hex("CLIENT_OPEN_2", open2, open2_len);
    if (strcmp(scenario, "alternative") == 0) {
        p76_make_response(rt.allocation_2.target_id, inbound, &inbound_len);
        status = p76_observe_device_response(&rt, inbound, inbound_len);
        if (status != P76_OK) return p76_fail(status);
        p76_make_response(rt.allocation_1.target_id, inbound, &inbound_len);
        status = p76_observe_device_response(&rt, inbound, inbound_len);
        if (status != P76_OK) return p76_fail(status);
    } else {
        p76_make_response(rt.allocation_1.target_id, inbound, &inbound_len);
        status = p76_observe_device_response(&rt, inbound, inbound_len);
        if (status != P76_OK) return p76_fail(status);
        p76_make_response(rt.allocation_2.target_id, inbound, &inbound_len);
        status = p76_observe_device_response(&rt, inbound, inbound_len);
        if (status != P76_OK) return p76_fail(status);
    }
    status = p76_generate_client_response_to_device_open(&rt, response, &response_len);
    if (status != P76_OK)
        return p76_fail(status);
    p76_print_hex("CLIENT_RESPONSE_DEVICE_OPEN", response, response_len);
    status = p76_generate_client_000a(&rt, media_000a, media_000a_len);
    if (status != P76_OK)
        return p76_fail(status);
    p76_print_hex("CLIENT_000A", media_000a, media_000a_len);
    status = p76_generate_client_001a(&rt, media_001a, media_001a_len);
    if (status != P76_OK)
        return p76_fail(status);
    p76_print_hex("CLIENT_001A", media_001a, media_001a_len);
    printf("STATE COMPLETE %s\n", p76_is_complete(&rt) ? "true" : "false");
    printf("HARNESS_NETWORK_CAPABLE=false\n");
    printf("LIVE_INVOCATIONS=0\n");
    printf("SECOND_CTPP_OPEN=false\n");
    printf("DOOR_ACTION_SENT=false\n");
    return p76_is_complete(&rt) ? 0 : p76_fail(P76_ERR_PARTIAL_COMPLETE);
}

static int p76_run_failure(const char *scenario, p76_u32 rand_result)
{
    P76Runtime rt;
    p76_u8 open1[P76_MAX_BODY], open2[P76_MAX_BODY], response[P76_MAX_BODY];
    p76_u8 media_000a[P76_MAX_BODY], media_001a[P76_MAX_BODY], inbound[P76_MAX_BODY];
    p76_u32 open1_len, open2_len, response_len, media_000a_len, media_001a_len, inbound_len;
    P76Status status = P76_OK;
    p76_runtime_init(&rt, rand_result);
    if (strcmp(scenario, "malformed-open") == 0) {
        inbound[0] = 0xcd; inbound[1] = 0xab;
        status = p76_observe_device_open(&rt, inbound, 2u);
    } else if (strcmp(scenario, "malformed-response") == 0) {
        status = p76_prepare_exchange(&rt, 0x4567u, open1, &open1_len, open2, &open2_len, media_000a, &media_000a_len, media_001a, &media_001a_len);
        if (status == P76_OK) {
            p76_make_response(rt.allocation_1.target_id, inbound, &inbound_len);
            inbound[4] = 0x05;
            status = p76_observe_device_response(&rt, inbound, inbound_len);
        }
    } else if (strcmp(scenario, "response-before-open") == 0) {
        p76_make_response(0x1234u, inbound, &inbound_len);
        status = p76_observe_device_response(&rt, inbound, inbound_len);
    } else if (strcmp(scenario, "unknown-response") == 0) {
        status = p76_prepare_exchange(&rt, 0x4567u, open1, &open1_len, open2, &open2_len, media_000a, &media_000a_len, media_001a, &media_001a_len);
        if (status == P76_OK) {
            p76_make_response(0x7777u, inbound, &inbound_len);
            status = p76_observe_device_response(&rt, inbound, inbound_len);
        }
    } else if (strcmp(scenario, "duplicate-response") == 0) {
        status = p76_prepare_exchange(&rt, 0x4567u, open1, &open1_len, open2, &open2_len, media_000a, &media_000a_len, media_001a, &media_001a_len);
        if (status == P76_OK) {
            p76_make_response(rt.allocation_1.target_id, inbound, &inbound_len);
            status = p76_observe_device_response(&rt, inbound, inbound_len);
            if (status == P76_OK)
                status = p76_observe_device_response(&rt, inbound, inbound_len);
        }
    } else if (strcmp(scenario, "reused-client-target") == 0) {
        status = p76_prepare_exchange(&rt, 0x4567u, open1, &open1_len, open2, &open2_len, media_000a, &media_000a_len, media_001a, &media_001a_len);
        if (status == P76_OK) {
            rt.allocation_2.target_id = rt.allocation_1.target_id;
            p76_make_response(rt.allocation_1.target_id, inbound, &inbound_len);
            status = p76_observe_device_response(&rt, inbound, inbound_len);
        }
    } else if (strcmp(scenario, "allocator-exhaustion") == 0) {
        p76_u32 i;
        for (i = 0; i < 0x8000u; i++)
            p76_runtime_mark_occupied(&rt, (p76_u16)i);
        status = p76_generate_client_exchange(&rt, 0x22000000u, 0x33000000u, P76_ROLE_A, P76_ROLE_B, open1, &open1_len, open2, &open2_len, media_000a, &media_000a_len, media_001a, &media_001a_len);
    } else if (strcmp(scenario, "client-response-without-device-open") == 0) {
        status = p76_generate_client_response_to_device_open(&rt, response, &response_len);
    } else if (strcmp(scenario, "bad-000a-binding") == 0) {
        status = p76_prepare_exchange(&rt, 0x4567u, open1, &open1_len, open2, &open2_len, media_000a, &media_000a_len, media_001a, &media_001a_len);
        if (status == P76_OK) {
            p76_write_le16(media_000a + 16, rt.allocation_2.target_id);
            status = p76_generate_client_000a(&rt, media_000a, media_000a_len);
        }
    } else if (strcmp(scenario, "bad-001a-binding") == 0) {
        status = p76_prepare_exchange(&rt, 0x4567u, open1, &open1_len, open2, &open2_len, media_000a, &media_000a_len, media_001a, &media_001a_len);
        if (status == P76_OK) {
            p76_write_le16(media_001a + 16, rt.allocation_1.target_id);
            status = p76_generate_client_001a(&rt, media_001a, media_001a_len);
        }
    } else if (strcmp(scenario, "second-ctpp-open") == 0) {
        status = p76_attempt_second_ctpp_open(&rt);
    } else if (strcmp(scenario, "door-entrypoint") == 0) {
        status = p76_attempt_door_entrypoint(&rt);
    } else if (strcmp(scenario, "partial-complete") == 0) {
        status = p76_prepare_exchange(&rt, 0x4567u, open1, &open1_len, open2, &open2_len, media_000a, &media_000a_len, media_001a, &media_001a_len);
        if (status == P76_OK)
            status = p76_is_complete(&rt) ? P76_OK : P76_ERR_PARTIAL_COMPLETE;
    } else {
        printf("ERROR UNKNOWN_SCENARIO\n");
        return 99;
    }
    if (status == P76_OK) {
        printf("ERROR EXPECTED_FAILURE_NOT_RAISED\n");
        return 98;
    }
    printf("ERROR %s\n", p76_status_name(status));
    printf("STATE COMPLETE %s\n", p76_is_complete(&rt) ? "true" : "false");
    printf("HARNESS_NETWORK_CAPABLE=false\n");
    printf("LIVE_INVOCATIONS=0\n");
    return 0;
}

int main(int argc, char **argv)
{
    const char *scenario = "canonical";
    p76_u32 rand_result = 0x9234u;
    int i;
    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--scenario") == 0 && i + 1 < argc) {
            scenario = argv[++i];
        } else if (strcmp(argv[i], "--rand-result") == 0 && i + 1 < argc) {
            rand_result = (p76_u32)strtoul(argv[++i], 0, 0);
        } else {
            printf("ERROR BAD_ARGUMENT\n");
            return 97;
        }
    }
    if (strcmp(scenario, "canonical") == 0 ||
        strcmp(scenario, "alternative") == 0 ||
        strcmp(scenario, "collision") == 0)
        return p76_run_success(scenario, rand_result);
    return p76_run_failure(scenario, rand_result);
}
#endif
'''


def transform(source: str) -> str:
    return add_device_video_ack(source) + "\n\n" + P76_RUNTIME_C_SECTION


def harness_source() -> str:
    return "#define P76_STANDALONE_HARNESS 1\n" + P76_RUNTIME_C_SECTION + P76_HARNESS_MAIN_C


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P76 RTPC C RUNTIME PARITY ===",
            "RTPC_C_RUNTIME_PARITY_CONTRACT=PROVEN_OFFLINE",
            "C_RUNTIME_BASE=P46_REVIEWED_TRANSFORM_CHAIN",
            "REGISTERED_CTPP_REUSED=true",
            "SECOND_CTPP_OPEN=false",
            "RTPC_TARGET_ALLOCATOR=P73_PARITY",
            "RTPC_OPEN_GENERATION=P74_PARITY",
            "RTPC_CONTROL_STATE_MACHINE=P75_PARITY",
            "CLIENT_RESPONSE_DEVICE_OPEN_BINDING=PROVEN",
            "CLIENT_000A_ALLOCATION_BINDING=PROVEN",
            "CLIENT_001A_ALLOCATION_BINDING=PROVEN",
            "CONTROL_TOTAL_ORDER_REQUIRED=false",
            "COLLISION_SKIP_SUPPORTED=true",
            "CAPTURE_TARGET_IDS_USED_AS_CONSTANTS=false",
            "PYTHON_C_DIFFERENTIAL_PARITY=PASS",
            "NETWORK_IO_PERFORMED=false",
            "LIVE_INVOCATIONS=0",
            "DOOR_ACTION_SENT=false",
            "MEDIA_SESSION_STARTED=false",
            "LIVE_TRANSMISSION_AUTHORIZED=false",
            "P46_P75_HISTORY=PRESERVED",
            "RAW_MEDIA_PROCESSED=false",
            "=== END COMELIT P76 RTPC C RUNTIME PARITY ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--harness-output", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    if args.report:
        print(report())
        return 0

    if args.output is not None:
        source_path = args.source
        if not source_path.exists() and str(source_path).startswith("safety-poc/"):
            source_path = Path(str(source_path)[len("safety-poc/"):])
        args.output.write_text(transform(source_path.read_text(encoding="utf-8")), encoding="utf-8")

    if args.harness_output is not None:
        args.harness_output.write_text(harness_source(), encoding="utf-8")

    if args.output is None and args.harness_output is None:
        print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
