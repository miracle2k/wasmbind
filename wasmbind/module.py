import dataclasses
import functools
from collections import Sequence
from inspect import isclass
from typing import Dict, Any, Iterable, Union, Optional, List, TypeVar
import json
from weakref import WeakValueDictionary

import wasmer

from wasmbind.low_level import ID_OFFSET, SIZE_OFFSET, REFCOUNT_OFFSET, STRING_ID, ARRAYBUFFER_ID, ARRAYBUFFERVIEW, \
    ARRAY, VAL_ALIGN_OFFSET, VAL_SIGNED, VAL_FLOAT, VAL_MANAGED, ARRAYBUFFERVIEW_BUFFER_OFFSET, \
    ARRAYBUFFERVIEW_DATASTART_OFFSET, ARRAYBUFFERVIEW_DATALENGTH_OFFSET, ARRAYBUFFERVIEW_SIZE, ARRAY_LENGTH_OFFSET, \
    ARRAY_SIZE, load_string, get_array_view_class, allocate_string

WasmMemPointer = int


class OpaqueValue:
    """Represents a value registered in the modules opaque value registry.
    """

    def __init__(self, id):
        self.id = id


class AssemblyScriptObject:
    """An opaque Python object wrapping a AssemblyScript object.

    This Python object keeps a reference to the AS object in WASM memory, and once the object
    has been GCed in Python, it will decrease the AS reference count.
    """

    _id: str
    _module = None

    def __del__(self):
        self._module.release(self._id)

    def __repr__(self):
        return f'<{type(self).__name__}@{self._id}>'

    def __eq__(self, other):
        if isinstance(other, AssemblyScriptObject):
            return self._id == other._id
        return False

    @classmethod
    def create(cls, pointer: WasmMemPointer, *, module):
        obj = object.__new__(cls)
        obj._id = pointer
        obj._module = module
        module.retain(pointer)
        return obj

    def as_(self, type):
        return self._module.resolve(self._id, as_=type)

    def __init__(self):
        raise TypeError("Use .create()")


class AssemblyScriptClass(AssemblyScriptObject):
    pass


class AssemblyScriptArray(AssemblyScriptObject, Sequence):

    _length = None
    _buffer_view = None
    _managed_class = None

    # noinspection PyMethodOverriding
    @classmethod
    def create(cls, pointer: WasmMemPointer, *, length: int, buffer_view, managed_class=None, module):
        array = super().create(pointer, module=module)
        array._length = length
        array._buffer_view = buffer_view
        array._id = pointer
        array._managed_class = managed_class
        array._module = module
        return array

    def __len__(self):
        return self._length

    def __getitem__(self, idx: int):
        idx = validate_index(idx, self._length)
        value = self._buffer_view[idx]

        if self._managed_class:
            return self._module.resolve(value, self._managed_class)

        return value

    def __setitem__(self, idx: int, value):
        idx = validate_index(idx, self._length)

        if self._managed_class:
            value = self._module.resolve_pointer(value)

        self._buffer_view[idx] = value

    def __eq__(self, other):
        if super().__eq__(other):
            return True
        if isinstance(other, Sequence):
            return list(self) == other
        return False


def validate_index(idx: Union[int, slice], length: int) -> Union[int, slice]:
    if isinstance(idx, slice):
        return slice(idx.start, min(idx.stop, length), idx.step)

    if idx >= length:
        raise IndexError(idx)

    return idx


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

    def get_pointer(self, instance: Union[WasmMemPointer, AssemblyScriptObject]) -> WasmMemPointer:
        """Resolve a Python wrapper class to the AssemblyScript pointer.
        """
        if isinstance(instance, AssemblyScriptObject):
            return instance._id
        return instance

    def resolve(self, pointer: WasmMemPointer, as_: Optional[Any] = None) -> AssemblyScriptObject:
        """
        The reverse of `get_pointer()`.
        """
        if isinstance(pointer, AssemblyScriptObject):
            # You should use pointer.as_() instead.
            return pointer

        # Opaque values are special, handle them first.
        if isclass(as_) and issubclass(as_, OpaqueValue):
            if pointer in self._opaque_values_weak:
                return self._opaque_values_weak[pointer]
            elif pointer in self._opaque_values:
                return self._opaque_values[pointer]
            else:
                raise ValueError("The opaque value registry only as weak references, and the value you registered no longer exists.")

        # Since the use of as_ implies that this is an AssemlblyScript object, we can check what the type really
        # is. This can serve for auto-detecting the type, or warning the user that the desired type is wrong.
        type = self.get_type_of(pointer)
        if type.has(ARRAYBUFFERVIEW):
            auto_detected = List
        elif type.has(ARRAY):
            auto_detected = List
        elif type.id == STRING_ID:
            auto_detected = str
        else:
            auto_detected = None

        if not as_:
            as_ = auto_detected

        # What is a good istypevar() check?
        if hasattr(as_, '__args__') and as_._name == 'List':
            arg = as_.__args__[0]
            if not isinstance(arg, TypeVar):
                return self.resolve_array(pointer, managed_class=arg)
            else:
                return self.resolve_array(pointer)

        if isclass(as_) and issubclass(as_, AssemblyScriptObject):
            return as_.create(pointer=pointer, module=self)

        if isclass(as_) and issubclass(as_, str):
            return load_string(pointer, instance=self.instance)

        raise ValueError("Unsupported _as: " + str(as_))

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

    def get_type_of(self, pointer: Union[WasmMemPointer, AssemblyScriptObject]) -> RTTIType:
        """Return the type of a pointer.
        """
        pointer = self.get_pointer(pointer)
        view = self.instance.memory.uint32_view((pointer + ID_OFFSET) // 4)
        type_id = view[0]
        return self.load_type(type_id)

    def get_refcount_of(self, pointer: Union[WasmMemPointer, AssemblyScriptObject]) -> RTTIType:
        """Return the refcount of a pointer.
        """
        pointer = self.get_pointer(pointer)
        view = self.instance.memory.uint32_view((pointer + REFCOUNT_OFFSET) // 4)
        return view[0]

    def resolve_array(self, pointer: WasmMemPointer, *, managed_class = None):
        """
        A live view on an array's values in the module's memory.

        Infers the array type from RTTI.
        """
        type = self.get_type_of(pointer)
        if not (type.has(ARRAYBUFFERVIEW) or type.has(ARRAY)):
            raise TypeError(f"The object at {pointer} is not an array.")

        u32_view = self.instance.memory.uint32_view()

        buffer_pointer = u32_view[(pointer + ARRAYBUFFERVIEW_DATASTART_OFFSET) // 4]
        length = u32_view[(pointer + ARRAY_LENGTH_OFFSET) // 4] \
            if type.has(ARRAY) \
            else u32_view[(buffer_pointer + SIZE_OFFSET) // 4]

        klass = get_array_view_class(
            self.instance, is_float=type.has(VAL_FLOAT), is_signed=type.has(VAL_SIGNED), alignment=type.value_align)
        array_buffer_view = klass(buffer_pointer >> type.value_align)

        is_managed = type.has(VAL_MANAGED)
        return AssemblyScriptArray.create(
            pointer,
            length=length, buffer_view=array_buffer_view, module=self,
            managed_class=(managed_class or AssemblyScriptObject) if is_managed else None)

    def alloc_array(self, type_id: int, values):
        """
        Allocate an array.

        - https://github.com/AssemblyScript/assemblyscript/blob/e79155b86b1ea29798a1d7d38dbe4a443c91310b/lib/loader/index.js#L160
        - https://docs.assemblyscript.org/details/memory#internals
        """

        type = self.load_type(type_id)
        if not type.has(ARRAYBUFFERVIEW | ARRAY):
            raise TypeError(f"{type} is not an array type. If you want to use this type in an array, you need to"
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

        # NB: >>> align will divide the 8bit pointers by the size of the array elements.
        view_class = get_array_view_class(
            self.instance,
            is_float=type.has(VAL_FLOAT), alignment=align, is_signed=type.has(VAL_SIGNED))
        array_buffer_view = view_class(array_buffer_pointer >> align)

        if type.has(VAL_MANAGED):
            for idx, value in enumerate(values):
                # For now, only allow classes to be added for consistency; we don't want to deal with ref counting
                # pointer values.
                if isinstance(value, str):
                    array_buffer_view[idx] = self.retain(allocate_string(value, instance=self.instance))
                else:
                    assert isinstance(value, AssemblyScriptObject)
                    array_buffer_view[idx] = self.retain(self.get_pointer(value))
        else:
            array_buffer_view[:length] = values

        return AssemblyScriptArray.create(
            array_pointer, length=length, buffer_view=array_buffer_view, module=self,
            managed_class=AssemblyScriptObject if type.has(VAL_MANAGED) else None)

    _opaque_values_weak = WeakValueDictionary()
    _opaque_values = {}
    _last_opaque_id = 0
    def register_opaque_value(self, value):
        """Register a value in a Python-side only registry. You will receive an integer you can pass to
        AssemblyScript, which can pass it back out, and it will resolve to the original value.
        """
        self._last_opaque_id += 1
        obj = object.__new__(OpaqueValue)
        obj._id = self._last_opaque_id

        # Builtin types do not support weekrefs, but we do not want to hold on to references if we don't have to.
        # https://stackoverflow.com/a/52011601/15677
        if getattr(type(value), '__weakrefoffset__', 0) > 0:
            self._opaque_values_weak[obj._id] = value
        else:
            self._opaque_values[obj._id] = value
        return obj


def convert(v, *, module: AssemblyScriptModule):
    if isinstance(v, AssemblyScriptObject):
        return module.get_pointer(v)

    elif isinstance(v, OpaqueValue):
        return v._id

    elif isinstance(v, str):
        return allocate_string(v, instance=module.instance)

    else:
        return v


def map_wasm_values(values: Iterable[Any], *, module: AssemblyScriptModule):
    """
    Replaces any `WasmRefValue` in `values` with the wasm id number.
    """
    return [convert(v, module=module) for v in values]


def make_function(f, *, module: AssemblyScriptModule):
    @functools.wraps(f)
    def wrapped(*args, as_=None):
        value = f(*map_wasm_values(args, module=module))
        if as_:
            return module.resolve(value, as_=as_)
        return value
    return wrapped


def make_method(f, *, module):
    return make_function(f, module=module)


def make_class(classname, class_exports: Dict, *, module: AssemblyScriptModule):
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

        attrs[name] = make_method(func, module=module)

    for name, definition in props.items():
        attrs[name] = property(
            make_method(definition['get'], module=module),
            make_method(definition['set'], module=module) if 'set' in definition else None,
        )

    def __new__(cls, *args):
        # [REFCOUNTS] The object returned by a class constructor is auto-retained (refcount = 1)
        _id = ctor(0, *map_wasm_values(args, module=module))
        obj = object.__new__(cls)
        obj._id = _id
        return obj

    def __init__(self, *a, **kw):
        pass

    def wrap(cls, pointer: WasmMemPointer):
        return cls.create(pointer, module=module)

    attrs.update({
        '_module': module,
        '__new__': __new__,
        '__init__': __init__,
        'wrap': classmethod(wrap)
    })

    return type(classname, (AssemblyScriptClass,), attrs)


class Module(AssemblyScriptModule):
    """
    Expects to be given the instance.exports from python-wasm-ext.
    """

    def __init__(self, instance: wasmer.Instance):
        AssemblyScriptModule.__init__(self, instance)

        # The only way to get those from wasmer-ext.
        export_names = json.loads(str(instance.exports))

        classdict = {}

        # Split the exports into classes
        exports_by_class = {}
        for name in export_names:
            func = getattr(instance.exports, name)

            if '#' in name:
                classname, funcname = name.split('#', 1)
                exports_by_class.setdefault(classname, {})
                exports_by_class[classname][funcname] = func

            elif name.startswith('__'):
                pass

            else:
                classdict[name] = make_function(func, module=self)

        # Create each class
        for classname, attrs in exports_by_class.items():
            classdict[classname] = make_class(classname, attrs, module=self)

        self.__dict__.update(classdict)

    def __getattr__(self, item):
        return getattr(self.instance.globals, item).value
