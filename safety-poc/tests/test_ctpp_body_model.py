import unittest

from comelit_safety_poc.body_reconciliation import DoorSemanticWrite, reconcile_structural_inventory
from comelit_safety_poc.ctpp_body_model import BuilderKind, parse_legacy_body_shape_inventory, synthesize_known_binary_body


REPORT = """=== LEGACY DOOR BODY SHAPE INVENTORY ===
SOURCE_SHA256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
SOURCE_HASH_PIN=PASS
SOURCE_EXECUTED=false
LITERAL_PAYLOAD_VALUES_PRINTED=false
SECRETS_READ=false
NETWORK_ACTION_PERFORMED=false
PHYSICAL_DOOR_ACTION=false

FUNCTION=_open_door_init
BINARY_BODY_BUILDER_CALLS=1
DOOR_MESSAGE_BUILDER_CALLS=0
WRITE_PACKET_CALLS=1
READ_RESPONSE_CALLS=2
BODY_CALL_1_LINE=430
BODY_CALL_1_COMPONENTS=2
BODY_CALL_1_REQUEST_ID_KIND=Attribute
BODY_CALL_1_COMPONENT_1_SHAPE=STRUCT_PACK(fmt='>H',argc=1)
BODY_CALL_1_COMPONENT_1_STATIC_BYTES=2
BODY_CALL_1_COMPONENT_2_SHAPE=CONST_BYTES(len=4)
BODY_CALL_1_COMPONENT_2_STATIC_BYTES=4

FUNCTION=open_door
BINARY_BODY_BUILDER_CALLS=1
DOOR_MESSAGE_BUILDER_CALLS=4
WRITE_PACKET_CALLS=5
READ_RESPONSE_CALLS=2
DOOR_MESSAGE_CALL_1_LINE=470
DOOR_MESSAGE_CALL_1_ARGC=2
DOOR_MESSAGE_CALL_1_ARG_SHAPES=ATTR(self.token)|NAME(door)
DOOR_MESSAGE_CALL_2_LINE=471
DOOR_MESSAGE_CALL_2_ARGC=2
DOOR_MESSAGE_CALL_2_ARG_SHAPES=ATTR(self.token)|NAME(door)
BODY_CALL_1_LINE=475
BODY_CALL_1_COMPONENTS=1
BODY_CALL_1_REQUEST_ID_KIND=Attribute
BODY_CALL_1_COMPONENT_1_SHAPE=STRUCT_PACK(fmt='>I',argc=1)
BODY_CALL_1_COMPONENT_1_STATIC_BYTES=4
DOOR_MESSAGE_CALL_3_LINE=480
DOOR_MESSAGE_CALL_3_ARGC=2
DOOR_MESSAGE_CALL_3_ARG_SHAPES=ATTR(self.token)|NAME(door)
DOOR_MESSAGE_CALL_4_LINE=481
DOOR_MESSAGE_CALL_4_ARGC=2
DOOR_MESSAGE_CALL_4_ARG_SHAPES=ATTR(self.token)|NAME(door)

LEGACY_DOOR_BODY_SHAPE_INVENTORY=PASS
PAYLOAD_LITERAL_VALUES_EXTRACTED=false
SOURCE_EXECUTED=false
SECRETS_READ=false
NETWORK_ACTION_PERFORMED=false
PHYSICAL_DOOR_ACTION=false
"""


class BodyModelTests(unittest.TestCase):
    def test_parses_six_writes_in_source_order_without_payload_values(self):
        inventory = parse_legacy_body_shape_inventory(REPORT)
        self.assertEqual(len(inventory.writes), 6)
        self.assertFalse(inventory.payload_values_extracted)
        self.assertEqual(tuple(write.builder_kind for write in inventory.writes), (
            BuilderKind.BINARY_PACKET_BODY,
            BuilderKind.DOOR_MESSAGE,
            BuilderKind.DOOR_MESSAGE,
            BuilderKind.BINARY_PACKET_BODY,
            BuilderKind.DOOR_MESSAGE,
            BuilderKind.DOOR_MESSAGE,
        ))

    def test_structural_reconciliation_maps_exact_semantic_order(self):
        reconciliation = reconcile_structural_inventory(parse_legacy_body_shape_inventory(REPORT))
        self.assertEqual(tuple(write.semantic for write in reconciliation.writes), tuple(DoorSemanticWrite))
        self.assertFalse(reconciliation.payload_values_present)
        self.assertFalse(reconciliation.byte_exact_body_reconciliation_complete)
        self.assertEqual(len({w.structural_fingerprint for w in reconciliation.writes}), 6)

    def test_binary_components_can_use_deterministic_synthetic_bytes_only(self):
        inventory = parse_legacy_body_shape_inventory(REPORT)
        first = synthesize_known_binary_body(inventory.writes[0])
        self.assertEqual(len(first), 6)
        self.assertEqual(first, synthesize_known_binary_body(inventory.writes[0]))
        with self.assertRaises(ValueError):
            synthesize_known_binary_body(inventory.writes[1])

    def test_unsafe_marker_rejected(self):
        with self.assertRaises(ValueError):
            parse_legacy_body_shape_inventory(REPORT.replace("SECRETS_READ=false", "SECRETS_READ=true"))


if __name__ == "__main__":
    unittest.main()
