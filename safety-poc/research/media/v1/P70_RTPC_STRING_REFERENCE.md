# P70: locate RTPC string references in the official Android DEX

P69 established that all three validated RTPC OPEN envelopes in the frozen
`self_activation.pcap` carry trailer scalar `1`, while explicitly leaving trailer
semantics and live body generation NOT_PROVEN.

P70 does not infer semantics from that scalar. Instead it uses the preserved
official Android application artifacts on CT120 and asks a narrower provenance
question: which managed-code methods actually load the literal `RTPC` string?

Observed read-only CT120 inputs:

- `classes7.dex` SHA-256 `851afb335a731c54e46ec39eb214a532c21c695eda6ce62de246b8d750e8f407`
- `classes8.dex` SHA-256 `05864bb668f26a7344217373f1d56fc8d38f71e92bf82f2cc9d82f20472c33ea`

Each DEX contains exactly one raw `RTPC` occurrence. Direct DEX parsing resolves
exactly one `const-string` reference in each file:

- `Lcom/comelit/bigapp/viper/ViperEnum$ViperChannelType;::<clinit>`
- `Lcom/comelitgroup/comelitvipkit/type/viper/Channel;::<clinit>`

Therefore the `RTPC` literal is bound to static initialization of two channel-type
enums in the official Android code. This is evidence that RTPC is represented as
a channel type in managed code; it does **not** yet prove how the 15-byte OPEN is
serialized, what byte 14 means, or whether scalar `1` is a stable generation
constant.

Safety scope of the observed run:

- no network I/O;
- no Comelit signaling;
- no listener changes;
- no Door action;
- no media activation or media payload inspection;
- no raw DEX bytes emitted;
- only file hashes, counts, class descriptors and method names emitted.

Next gate: inspect only the two identified enum static initializers and resolve the
constructor/static-field metadata associated with `RTPC`. Do not search for a
literal scalar `1` globally and do not promote P69's observed trailer to a live
contract until its provenance is established.
