# [REFCOUNTS]: https://docs.assemblyscript.org/details/runtime#rules, https://docs.assemblyscript.org/details/runtime#working-with-references-externally


# Before a data type, the memory stores the type and the size
# https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L3
import wasmer

ID_OFFSET = -8
SIZE_OFFSET = -4
REFCOUNT_OFFSET = - 12


# https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L8
STRING_ID = 1
# An array buffer is a type, with a header, that stores array data.
ARRAYBUFFER_ID = 0
# A TypedArray such as UInt8Array is a dynamic type, with this id as the base id. They all follow the same memory
# structure, which is defined as the structure of this base type.
# A normal Array<u8> is very similar, base this as the base, but adds an extra field.
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


def load_string(pointer: int, *, instance: wasmer.Instance):
    # Strings seems to be encoded as a utf-16 string, prefixed with a u32 giving the length.
    # https://github.com/AssemblyScript/docs/blob/master/standard-library/string.md
    # https://github.com/onsails/wasmer-as/blob/fe096b492d3c7a5f49214b76a7aff75fe6343c5f/src/lib.rs#L23
    # https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L43

    u32 = instance.memory.uint32_view(0)

    datatype = u32[int((pointer + ID_OFFSET) / 4)]
    assert datatype == STRING_ID

    string_length = u32[int((pointer + SIZE_OFFSET) / 4)]

    u8 = instance.memory.uint8_view(pointer)
    if string_length:
        string_bytes = u8[:string_length]
        return bytes(string_bytes).decode('utf-16')
    else:
        return ""


def allocate_string(v: str, *, instance: wasmer.Instance):
    # https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L120
    pointer = instance.exports.__alloc(len(v) * 2, STRING_ID)

    buffer = instance.memory.uint8_view(pointer)
    bytes = v.encode('utf-16le')  # Without BOM
    if bytes:
        buffer[:len(bytes)] = bytes

    lengthview = instance.memory.uint32_view(0)
    lengthview[int(pointer / 4) - 1] = len(bytes)
    return pointer


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