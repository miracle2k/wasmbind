# wasmbind

Wraps your WebAssembly exports to provide you are with a more usable interface in Python. 
Currently works with [AssemblyScript](https://assemblyscript.org/) modules, and 
[python-ext-wasm](https://github.com/wasmerio/python-ext-wasm) as the loader.

In doing so, it tries to play a similar role as [wasm-bindgen](https://github.com/rustwasm/wasm-bindgen) 
or [as-bind](https://github.com/torch2424/as-bind) in JavaScript.

Install with `pip install wasmbind` or [`poetry add wasmbind`](https://github.com/python-poetry/poetry).

**WARNING**: As of this writing, the latest published version 0.3 of `python-ext-wasm` is not supported;
you need to run on git master. The released version does not allow us to access the WASM memory. 


## Features

Features: 

- ✅ Strings, Arrays, Maps, Custom Classes.
- ✅ Work with AssemblyScript objects in Python.
- ✅ Instantiate new AssemblyScript objects in Python. 

Future plans:

- [ ] Allow wrapping arrays returned from WASM.
- [ ] Improve array allocation by finding available types in RTTI.
- [ ] Improve these docs.
- [ ] See if we can use RTTI to remove the need for a manual `as_`. We might have to create a class registry
      similar to [as-bind](https://github.com/torch2424/as-bind/blob/97353ef6f8e39a4277957079b5d6a9e7d85ee709/lib/assembly/as-bind.ts)
- [ ] Investigate an alternative approach wherein you predefine classes (with types) in Python code.
- [ ] Allow creation of types without a constructor.


## Usage

Setup your module like this:

```python
from wasmer import Instance
wasm = Instance(open('yourscript.wasm', 'rb').read())

from wasmbind import Module
module = Module(wasm)
```

Here are some sample interactions.

#### Strings

```typescript
export function helloworld(name: string): string {
    return "hello, " + name
}
```

```python
>>> module.helloworld("michael", as_=str)
"hello, michael"
```

You'll note that you have to specificy the desired return type via `as_`. This is because WASM only
gives us a pointer to a memory location, and we otherwise have no idea what the type is. See the section
`Resolving Return Values` for other options.

Passing values *into* AssemblyScript works, because we know it the type. In this case, we can allocate
a `string` on the AssemblyScript side and pass the pointer to it into `helloworld`.

Note: You'll get a real Python `str` from AssemblyScript, and you are expected to pass real `str` 
objects to AssemblyScript functions. Strings are immutable in AssemblyScript and Python. Those
things mean that for the boundary Python <-> AssemblyScript, they are passed by value and copied. No
reference counting is involved.


#### Objects & Properties

```typescript
export class File {
  constructor(
    public size: i32,
  ) {}
}
```

```python
>>> dir = module.Directory(3)
>>> dir.size
3
>>> dir.size = 10
>>> dir.size
10
```

#### Objects

```typescript
export class Line {
  constructor(
    public s: string
  ) {}
}

export class File {
  public lines: Line[] = []

  constructor() {}
  
  addLine(line: Line): number {
    this.lines.push(line);
    return this.lines.length; 
  }
}
```

```python
>>> file = module.File()
>>> line = module.Line("line 1")
>>> file.addLine(line)
1
```

#### Maps and other generic types
 
Let's say you have a function that takes a map as an argument:

```typescript
export function getMap(): Map<string, i32> {
  return new Map();
}
```

First, if you look into this module's exports, you will note that there is only `getMap()`. The 
`Map` class itself was not exported. 

Now, if you add `export {Map}`, depending on your code, you might see exports such as:

```
'Map<~lib/string/String,~lib/string/String>#get', 'Map<i32,i32>#constructor', 'Map<i32,i32>#clear'
```

Every concrete version of the generic `Map` type is exported separately, the names aren't 
very nice, and finally, the classes are incomplete: Only methods which were used at some
point in your code are exported, the rest, I assume, have been optimized away.

Currently, `wasmbind` does not do anything special with those exports, which means you can
use them, but they are not very accessible.

The best way to use a map, which I have found so far, is this:

```typescript
export class StringMap extends Map<string, string> {};
```

This will give you a complete and fully-functional `StringMap` class in Python.


## Resolving Return Values

Options for the future:

```python
# Every return value is a a Opaque Type that you can either call .native() on or .as().
module = Module(instance, value_handler=wrap_opaque)

# Every return value is auto-instantiated via the object header 
module = Module(instance, value_handler=auto_resolve)

# Using mypy to predefine the return types of each method and function call. 
module = Module(instance, class_registry={})
```


## Notes

In part, this is a port of the AssemblyScript loader. The following links were helpful in implementing this:

- [AssemblyScript Loader code](https://github.com/AssemblyScript/assemblyscript/blob/master/lib/loader/index.js)
- [AssemblyScript Loader docs](https://docs.assemblyscript.org/basics/loader#why-not-more-convenient)
- [wasmer-as code](https://github.com/onsails/wasmer-as)
- [as-bind code](https://github.com/torch2424/as-bind)
- [python-ext-wasm docs](https://github.com/wasmerio/python-ext-wasm)