import functools
from typing import Dict, List, Any, Iterable
import json

import wasmer


class WasmRefValue:
    """This base class indicates the subclass returns the wasm id via hash().
    """
    pass


def map_wasm_values(values: Iterable[Any]):
    """
    Replaces any `WasmRefValue` in `values` with the wasm id number.
    """
    return [
        hash(v) if isinstance(v, WasmRefValue) else v
        for v in values
    ]


def make_function(f):
    @functools.wraps(f)
    def wrapped(*args, as_=None):
        result = f(*map_wasm_values(args))
        if as_:
            instance = object.__new__(as_)
            instance.__dict__['__id'] = result
            return instance
        return result
    return wrapped


def make_method(f):
    return lambda self, *args: f(hash(self), *map_wasm_values(args))


def make_class(classname, class_exports: Dict):
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

        attrs[name] = make_method(func)

    for name, definition in props.items():
        attrs[name] = property(
            make_method(definition['get']),
            make_method(definition['set']),
        )

    def __init__(self, *args):
        self.__id = ctor(0, *map_wasm_values(args))

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

        # Split the exports into classes
        exports_by_class = {}
        for name in export_names:
            func = getattr(instance.exports, name)

            if '#' in name:
                classname, funcname = name.split('#', 1)
                exports_by_class.setdefault(classname, {})
                exports_by_class[classname][funcname] = func
            else:
                classdict[name] = make_function(func)

        # Create each class
        for classname, attrs in exports_by_class.items():
            classdict[classname] = make_class(classname, attrs)

        instance = object.__new__(cls)
        instance.__dict__.update(classdict)
        return instance

