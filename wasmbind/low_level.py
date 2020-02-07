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
    string_bytes = u8[:string_length]
    return bytes(string_bytes).decode('utf-16')