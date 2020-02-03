import functools
from typing import Dict, Any, Iterable
import json

import wasmer


# https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L8
ARRAYBUFFER_ID = 0
STRING_ID = 1
ARRAYBUFFERVIEW_ID = 2


class WasmRefValue:
    """This base class indicates the subclass returns the wasm id via hash().
    """
    pass


def map_wasm_values(values: Iterable[Any], *, instance: wasmer.Instance):
    """
    Replaces any `WasmRefValue` in `values` with the wasm id number.
    """
    def convert(v):
        if isinstance(v, WasmRefValue):
            return v
        elif isinstance(v, str):
            # https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L120
            pointer = instance.exports.__alloc(len(v) * 2, STRING_ID)

            buffer = instance.memory.uint8_view(pointer)
            bytes = v.encode('utf-16')
            buffer[:len(bytes)] = bytes

            lengthview = instance.memory.uint32_view(0)
            lengthview[int(pointer / 4) - 1] = len(bytes)

            return pointer
        else:
            return v

    return [convert(v) for v in values]


def make_function(f, *, instance: wasmer.Instance):
    @functools.wraps(f)
    def wrapped(*args, as_=None):
        value = f(*map_wasm_values(args, instance=instance))
        if as_:
            if issubclass(as_, WasmRefValue):
                obj = object.__new__(as_)
                obj.__dict__['__id'] = value
                return obj

            if issubclass(as_, str):
                # Strings seems to be encoded as a utf-16 string, prefixed with a u32 giving the length.
                # https://github.com/AssemblyScript/docs/blob/master/standard-library/string.md
                # https://github.com/onsails/wasmer-as/blob/fe096b492d3c7a5f49214b76a7aff75fe6343c5f/src/lib.rs#L23
                # https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L43

                u32 = instance.memory.uint32_view(0)
                string_length = u32[int(value / 4) - 1]
                print(string_length)

                u8 = instance.memory.uint8_view(value)
                string_bytes = u8[:string_length]
                return bytes(string_bytes).decode('utf-16')

            raise ValueError("Unsupported _as: " + str(as_))
        return value
    return wrapped


def make_method(f, *, instance):
    return make_function(f, instance=instance)


def make_class(classname, class_exports: Dict, *, instance: wasmer.Instance):
    """Create a Python class from a AssemblyScript class.
    """
    # If the AssemblyScript class defines no constructor, I am not sure how we can create the object.
    if not 'constructor' in class_exports:
        return None

    ctor = class_exports.pop('constructor')

    attrs = {}
    props = {}
    for name, func in class_exports.items():
        if ':' in name:
            op, propname = name.split(':')
            if op in ('set', 'get'):
                props.setdefault(propname, {})[op] = func
                continue

        attrs[name] = make_method(func, instance=instance)

    for name, definition in props.items():
        attrs[name] = property(
            make_method(definition['get'], instance=instance),
            make_method(definition['set'], instance=instance),
        )

    def __init__(self, *args):
        self.__id = ctor(0, *map_wasm_values(args, instance=instance))

    def __hash__(self):
        return self.__id

    attrs.update({
        '__init__': __init__,
        '__hash__': __hash__,
    })

    return type(classname, (WasmRefValue,), attrs)


class Module:
    """
    Expects to be given the instance.exports from python-wasm-ext.
    """

    def __new__(cls, instance: wasmer.Instance):
        # The only way to get those from wasmer-ext.
        export_names = json.loads(str(instance.exports))
        print(export_names)

        classdict = {}
        allocator = {}

        # Split the exports into classes
        exports_by_class = {}
        for name in export_names:
            func = getattr(instance.exports, name)

            if '#' in name:
                classname, funcname = name.split('#', 1)
                exports_by_class.setdefault(classname, {})
                exports_by_class[classname][funcname] = func
            if name.startswith('__'):
                allocator[name[2:]] = func
            else:
                classdict[name] = make_function(func, instance=instance)

        # Create each class
        for classname, attrs in exports_by_class.items():
            classdict[classname] = make_class(classname, attrs, instance=instance)

        # Create the allocator
        allocator = make_class("Allocator", allocator, instance=instance)

        instance = object.__new__(cls)
        instance.__dict__.update(classdict)
        return instance

