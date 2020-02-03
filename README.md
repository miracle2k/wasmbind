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

Supported: 

- Ability to exchange strings and custom classes.

Note: Currently, if your class does not define a constructor, it will not be exposed.

Future plans:

- [ ] Investigate correct memory management
- [ ] Support arrays
- [ ] See if we can use RTTI to remove the need for a manual `as_`.
- [ ] Investigate an alternative approach wherein you predefine classes (with types) in Python code.


## Usage

Setup your module like this:

```python
from wasmer import Instance
wasm = Instance(open('yourscript.wasm', 'rb').read())

from wasmbind import Module
module = Module(wasm)
```

Here are some sample interactions.

With strings:

```typescript
export function helloworld(name: string): string {
    return "hello, " + name
}
```

```python
>>> module.helloworld("michael")
"hello, michael" 
```

Properties:

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

Objects:

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


## Notes

In part, this is a port of the AssemblyScript loader. The following links were helpful in implementing this:

- [AssemblyScript Loader code](https://github.com/AssemblyScript/assemblyscript/blob/master/lib/loader/index.js)
- [AssemblyScript Loader docs](https://docs.assemblyscript.org/basics/loader#why-not-more-convenient)
- [wasmer-as code](https://github.com/onsails/wasmer-as)
- [as-bind code](https://github.com/torch2424/as-bind)
- [python-ext-wasm docs](https://github.com/wasmerio/python-ext-wasm)