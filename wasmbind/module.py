import dataclasses
import functools
from typing import Dict, Any, Iterable, List, Tuple, Union
import json

import wasmer


# [REFCOUNTS]: https://docs.assemblyscript.org/details/runtime#rules, https://docs.assemblyscript.org/details/runtime#working-with-references-externally


# Before a data type, the memory stores the type and the size
# https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L3
ID_OFFSET = -8
SIZE_OFFSET = -4
REFCOUNT_OFFSET = - 12


# https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L8
ARRAYBUFFER_ID = 0
STRING_ID = 1
ARRAYBUFFERVIEW_ID = 2

# Runtime type information flags
# https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L12
ARRAYBUFFERVIEW = 1 << 0
ARRAY = 1 << 1
SET = 1 << 2
MAP = 1 << 3
VAL_ALIGN_OFFSET = 5
VAL_ALIGN = 1 << VAL_ALIGN_OFFSET
VAL_SIGNED = 1 << 10
VAL_FLOAT = 1 << 11
VAL_NULLABLE = 1 << 12
VAL_MANAGED = 1 << 13
KEY_ALIGN_OFFSET = 14
KEY_ALIGN = 1 << KEY_ALIGN_OFFSET
KEY_SIGNED = 1 << 19
KEY_FLOAT = 1 << 20
KEY_NULLABLE = 1 << 21
KEY_MANAGED = 1 << 22


# Array(BufferView) layout
# https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L30
ARRAYBUFFERVIEW_BUFFER_OFFSET = 0
ARRAYBUFFERVIEW_DATASTART_OFFSET = 4
ARRAYBUFFERVIEW_DATALENGTH_OFFSET = 8
ARRAYBUFFERVIEW_SIZE = 12
ARRAY_LENGTH_OFFSET = 12
ARRAY_SIZE = 16


WasmMemPointer = int


class WasmClass:
    """This base class indicates the subclass returns the wasm id via hash().
    """
    pass


# https://codegolf.stackexchange.com/a/177280
clz32 = lambda n:35-len(bin(-n))&~n>>32


@dataclasses.dataclass
class RTTIType:
    id: int
    base_id: int
    flags: int

    def has(self, flag: int) -> bool:
        return bool(self.flags & flag)

    @property
    def value_align(self):
        # https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L110
        return 31 - clz32((self.flags >> VAL_ALIGN_OFFSET) & 31)   # -1 if none


class AssemblyScriptModule:

    def __init__(self, instance: wasmer.Instance):
        self.instance = instance

    @property
    def alloc(self):
        return getattr(self.instance.exports, '__alloc')

    @property
    def retain(self):
        return getattr(self.instance.exports, '__retain')

    @property
    def release(self):
        return getattr(self.instance.exports, '__release')

    def load_type(self, id: Union[int, RTTIType]) -> RTTIType:
        """From the RTTI section of the WASM memory, load information about the type with id `id`.

        The RTTI table is like this:

            [0] = num types
            [1:2] = type 1
            [4:4] = type 2
            ...

        Type ids are indices into that table. Every type has two u32. The first one is flag,
        the second one is the id of the base class.

        For more, see:
        - https://docs.assemblyscript.org/details/runtime#runtime-type-information-rtti
        - https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L94
        """
        if isinstance(id, RTTIType):
            return id

        rtti_base = getattr(self.instance.globals, '__rtti_base')
        if not rtti_base:
            # AssemblyScript loader says "oop" in this case. I don't understand that or the code path.
            raise ValueError('RTTI table not found.')
        view = self.instance.memory.uint32_view(rtti_base.value // 4)
        count = view[0]
        assert id < count

        mem_index = 1 + id * 2
        return RTTIType(id=id, base_id=view[mem_index+1], flags=view[mem_index])

    def get_type_of(self, pointer: Union[WasmMemPointer, WasmClass]) -> RTTIType:
        """Return the type of a pointer.
        """
        if isinstance(pointer, WasmClass):
            pointer = hash(pointer)
        view = self.instance.memory.uint32_view((pointer + ID_OFFSET) // 4)
        type_id = view[0]
        return self.load_type(type_id)

    def get_pointer(self, instance: Union[WasmMemPointer, WasmClass]) -> WasmMemPointer:
        """Resolve a Python wrapper class to the AssemblyScript pointer.
        """
        if isinstance(instance, WasmClass):
            return hash(instance)
        return instance

    def get_refcount_of(self, pointer: Union[WasmMemPointer, WasmClass]) -> RTTIType:
        """Return the refcount of a pointer.
        """
        if isinstance(pointer, WasmClass):
            pointer = hash(pointer)
        view = self.instance.memory.uint32_view((pointer + REFCOUNT_OFFSET) // 4)
        return view[0]

    def alloc_array(self, type_id: int, values):
        """
        Allocate an array.

        - https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L160
        - https://docs.assemblyscript.org/details/memory#internals
        """

        type = self.load_type(type_id)
        if not type.has(ARRAYBUFFERVIEW | ARRAY):
            raise ValueError(f"{type} is not an array type. If you want to use this type in an array, you need to"
                             f"create a concrete array type for it.")

        length = len(values)
        align = type.value_align

        # Allocate an array buffer pointer to store the actual data, with the desired length
        array_buffer_pointer = self.alloc(length << align, ARRAYBUFFER_ID)

        # Allocate an array
        array_pointer = self.alloc(ARRAY_SIZE if type.has(ARRAY) else ARRAYBUFFERVIEW_SIZE, type_id)
        array_view = self.instance.memory.uint32_view(array_pointer // 4)
        array_view[ARRAYBUFFERVIEW_BUFFER_OFFSET // 4] = self.retain(array_buffer_pointer)
        array_view[ARRAYBUFFERVIEW_DATASTART_OFFSET // 4] = array_buffer_pointer
        array_view[ARRAYBUFFERVIEW_DATALENGTH_OFFSET // 4] = length << align
        if type.has(ARRAY):
            array_view[ARRAY_LENGTH_OFFSET // 4] = length

        if type.has(VAL_MANAGED):
            # for (let i = 0; i < length; ++i) view[(buf >>> align) + i] = retain(values[i]);
            raise ValueError("Arrays with reference types not yet supported.")
        else:
            # we want to write to array_buffer_pointer (divided by /align because that is the view we will use)
            view_class = get_array_view_class(
                self.instance,
                is_float=type.has(VAL_FLOAT), alignment=align, is_signed=type.has(VAL_SIGNED))
            array_view = view_class(array_buffer_pointer >> align)
            array_view[:length] = values

        return array_pointer


def get_array_view_class(instance: wasmer.Instance, *, is_float: bool, alignment: int, is_signed: bool):
    """Given the requested array configuration, return a view class that can be used over the memory segment
    of that array, to access and write to the elements of that WASM array in Python.
    """
    m = instance.memory
    if is_float:
        # For now, wasmer does not offer view classes for this; either wait for them to add them,
        # or implement one ourselves.
        raise ValueError("float arrays are not yet supported.")
    else:
        if alignment == 0:
            return m.int8_view if is_signed else m.uint8_view
        if alignment == 1:
            return m.int16_view if is_signed else m.uint16_view
        if alignment == 2:
            return m.int32_view if is_signed else m.uint32_view
        if alignment == 3:
            # For now, wasmer does not offer a view class for this; either wait for them to add one, or
            # implement one ourselves.
            raise ValueError("64bit arrays are not yet supported.")

    raise ValueError("Invalid align value.")


def map_wasm_values(values: Iterable[Any], *, instance: wasmer.Instance):
    """
    Replaces any `WasmRefValue` in `values` with the wasm id number.
    """
    def convert(v):
        if isinstance(v, WasmClass):
            return hash(v)

        elif isinstance(v, str):
            # https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L120
            pointer = instance.exports.__alloc(len(v) * 2, STRING_ID)

            buffer = instance.memory.uint8_view(pointer)
            bytes = v.encode('utf-16le')  # Without BOM
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
            if issubclass(as_, WasmClass):
                obj = object.__new__(as_)
                obj.__dict__['__id'] = value
                return obj

            if issubclass(as_, str):
                # Strings seems to be encoded as a utf-16 string, prefixed with a u32 giving the length.
                # https://github.com/AssemblyScript/docs/blob/master/standard-library/string.md
                # https://github.com/onsails/wasmer-as/blob/fe096b492d3c7a5f49214b76a7aff75fe6343c5f/src/lib.rs#L23
                # https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L43

                u32 = instance.memory.uint32_view(0)

                datatype = u32[int((value + ID_OFFSET) / 4)]
                assert datatype == STRING_ID

                string_length = u32[int((value + SIZE_OFFSET) / 4)]

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

    It:

    - Wraps the pointer to the value.
    - Creates methods and properties as exported by the module.
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
        # [REFCOUNTS] The object returned by a class constructor is auto-retained (refcount = 1)
        self.__id = ctor(0, *map_wasm_values(args, instance=instance))

    def __hash__(self):
        return self.__id

    def __del__(self):
        instance.exports.__release(self.__id)

    attrs.update({
        '__init__': __init__,
        '__hash__': __hash__,
        '__del__': __del__,
    })

    return type(classname, (WasmClass,), attrs)


class Module(AssemblyScriptModule):
    """
    Expects to be given the instance.exports from python-wasm-ext.
    """

    def __init__(self, instance: wasmer.Instance):
        AssemblyScriptModule.__init__(self, instance)

        # The only way to get those from wasmer-ext.
        export_names = json.loads(str(instance.exports))

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

            elif name.startswith('__'):
                allocator[name[2:]] = func

            else:
                classdict[name] = make_function(func, instance=instance)

        # Create each class
        for classname, attrs in exports_by_class.items():
            classdict[classname] = make_class(classname, attrs, instance=instance)

        self.__dict__.update(classdict)

