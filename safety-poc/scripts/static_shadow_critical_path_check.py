#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
SHADOW_MODULE = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else REPO_ROOT / "custom_components" / "comelit" / "ring_shadow.py"
)

ALLOWED_IMPORTS = {"__future__", "collections", "dataclasses", "typing"}
ENTRYPOINTS = {
    "RingShadowHook.observe_line",
    "RingShadowHook.note_state",
    "RingShadowHook._invoke",
    "RingShadowController.observe_native_line",
    "RingShadowController.note_state",
    "RingMarkerBatcher.observe",
    "RingEmitGuard.decide",
}
BANNED_CALLS = {
    "sleep",
    "open",
    "Popen",
    "system",
    "popen",
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
    "urlopen",
    "create_connection",
    "sha256",
    "md5",
    "uuid4",
    "time",
    "monotonic",
    "fire",
    "async_fire",
}
BANNED_ATTR_ROOTS = {
    "asyncio",
    "socket",
    "aiohttp",
    "requests",
    "urllib",
    "subprocess",
    "os",
    "ssl",
}


def fail(reason: str) -> None:
    print(f"STATIC_SHADOW_CRITICAL_PATH_CHECK=FAIL {reason}")
    raise SystemExit(1)


def callable_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = callable_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        return callable_name(node.value)
    return None


def local_call_name(node: ast.Call, current_class: str | None) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "self"
        and current_class is not None
    ):
        return f"{current_class}.{func.attr}"
    return None


text = SHADOW_MODULE.read_text(encoding="utf-8")
tree = ast.parse(text)

imports: set[str] = set()
callables: dict[str, tuple[ast.AST, str | None]] = {}
class_stack: list[str] = []
deque_bound_names: set[str] = set()
deque_bound_attrs: set[str] = set()
deque_dataclass_attrs: set[str] = set()


class DefinitionVisitor(ast.NodeVisitor):
    def visit_Import(self, node: ast.Import) -> None:
        imports.update(alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            imports.add(node.module.split(".")[0])

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_stack.append(node.name)
        self.generic_visit(node)
        class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if class_stack:
            callables[f"{class_stack[-1]}.{node.name}"] = (node, class_stack[-1])
        else:
            callables[node.name] = (node, None)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        annotation = callable_name(node.annotation)
        if class_stack and annotation and annotation.endswith("Deque"):
            if isinstance(node.target, ast.Name):
                deque_dataclass_attrs.add(node.target.id)
        if isinstance(node.value, ast.Call):
            name = callable_name(node.value.func)
            short_name = name.rsplit(".", 1)[-1] if name else ""
            if short_name == "deque":
                target = node.target
                if isinstance(target, ast.Name):
                    deque_bound_names.add(target.id)
                elif (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    deque_bound_attrs.add(target.attr)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call):
            name = callable_name(node.value.func)
            short_name = name.rsplit(".", 1)[-1] if name else ""
            if short_name == "deque":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        deque_bound_names.add(target.id)
                    elif (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        deque_bound_attrs.add(target.attr)
        self.generic_visit(node)


DefinitionVisitor().visit(tree)

if not imports <= ALLOWED_IMPORTS:
    fail(f"imports={sorted(imports - ALLOWED_IMPORTS)}")

missing_entrypoints = sorted(name for name in ENTRYPOINTS if name not in callables)
if missing_entrypoints:
    fail(f"missing_entrypoints={missing_entrypoints}")

closure: set[str] = set()
pending = list(ENTRYPOINTS)
while pending:
    name = pending.pop()
    if name in closure:
        continue
    closure.add(name)
    node, current_class = callables[name]
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            called = local_call_name(child, current_class)
            if called in callables and called not in closure:
                pending.append(called)

if not closure:
    fail("empty_closure")

critical_nodes = [callables[name][0] for name in sorted(closure)]
critical_root_names = {name.rsplit(".", 1)[-1] for name in closure}

await_found = False
sleep_found = False
network_found = False
file_found = False
subprocess_found = False
unbounded_found = False

for node in ast.walk(tree):
    if isinstance(node, ast.AsyncFunctionDef):
        fail("async_function_present")

for root in critical_nodes:
    for node in ast.walk(root):
        if isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith)):
            await_found = True
        if isinstance(node, ast.Call):
            name = callable_name(node.func)
            short_name = name.rsplit(".", 1)[-1] if name else ""
            if short_name in BANNED_CALLS:
                if short_name in {"sleep", "time", "monotonic"}:
                    sleep_found = True
                elif short_name in {
                    "open",
                    "read_text",
                    "write_text",
                    "read_bytes",
                    "write_bytes",
                }:
                    file_found = True
                elif short_name in {"Popen", "system", "popen"}:
                    subprocess_found = True
                else:
                    network_found = True
            if name:
                root_name = name.split(".", 1)[0]
                if root_name in BANNED_ATTR_ROOTS:
                    if root_name in {"subprocess", "os"}:
                        subprocess_found = True
                    else:
                        network_found = True
            if short_name == "deque":
                maxlen_keywords = [
                    keyword.value
                    for keyword in node.keywords
                    if keyword.arg == "maxlen"
                ]
                if not maxlen_keywords:
                    unbounded_found = True
                else:
                    for value in maxlen_keywords:
                        if not (
                            isinstance(value, ast.Constant)
                            and isinstance(value.value, int)
                            and value.value > 0
                        ):
                            unbounded_found = True
            if (
                short_name in {"append", "appendleft"}
                and isinstance(node.func, ast.Attribute)
            ):
                target = node.func.value
                allowed_append = False
                if isinstance(target, ast.Name):
                    allowed_append = target.id in deque_bound_names
                elif (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    allowed_append = target.attr in deque_bound_attrs
                elif isinstance(target, ast.Attribute):
                    allowed_append = target.attr in deque_dataclass_attrs
                if not allowed_append:
                    unbounded_found = True
            if short_name in {"list", "set", "dict", "Counter"}:
                unbounded_found = True
        if isinstance(node, (ast.List, ast.Set, ast.Dict)):
            owner = root.name if isinstance(root, ast.FunctionDef) else ""
            if owner not in {"snapshot", "as_dict"} and owner in critical_root_names:
                unbounded_found = True

if await_found:
    fail("await_present")
if sleep_found:
    fail("sleep_present")
if network_found:
    fail("network_io_present")
if file_found:
    fail("file_io_present")
if subprocess_found:
    fail("subprocess_present")
if unbounded_found:
    fail("unbounded_storage_present")

print("STATIC_SHADOW_CRITICAL_PATH_CHECK=PASS")
print(f"SHADOW_CRITICAL_PATH_CLOSURE={len(closure)}")
print("CRITICAL_PATH_AWAIT=false")
print("CRITICAL_PATH_SLEEP=false")
print("CRITICAL_PATH_NETWORK_IO=false")
print("CRITICAL_PATH_FILE_IO=false")
print("CRITICAL_PATH_SUBPROCESS=false")
print("CRITICAL_PATH_UNBOUNDED_STORAGE=false")
print("SHADOW_MODULE_IMPORTS=__future__,collections,dataclasses,typing")
