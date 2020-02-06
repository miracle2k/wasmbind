def test_strings(from_code):
    module = from_code("""
    export function helloworld(s: string): string {
        return "foo:" + s
    }
    """)
    assert module.helloworld("foo", as_=str) == 'foo:foo'


def test_root_function(from_code):
    module = from_code("""
    export function sum(a: i32, b: i32): i32 {
        return a + b;
    }
    """)
    assert module.sum(1, 2) == 3


def test_properties(from_code):
    module = from_code("""
    export class Foo {
        constructor() {}
        public bar: i32 = 42;        
    }
    """)
    foo = module.Foo()
    assert foo.bar == 42
    foo.bar = 13
    assert foo.bar == 13


def test_return_an_object(from_code):
    module = from_code("""
    export class Foo {
        constructor() {}
        public bar: i32 = 42;        
    }
    export function getFoo(): Foo {
        return new Foo();        
    }
    """)

    assert isinstance(module.getFoo(), int)

    foo = module.getFoo(as_=module.Foo)
    assert foo.bar == 42


class TestRTTI:

    def test_get_type_from_pointer(self, from_code):
        module = from_code("""
        export class Foo { constructor() {} }
        export class Bar extends Foo { constructor() { super(); } }        
        """)
        foo_type = module.get_type_of(module.Foo())
        bar_type = module.get_type_of(module.Bar())
        assert bar_type.base_id == foo_type.id


class TestGarbageCollect:

    def test_manual_retain_calls(self, from_code):
        module = from_code("""
        export class Foo { constructor() {} }        
        """)

        foo = module.Foo()
        foo_pointer = module.get_pointer(foo)

        assert module.get_refcount_of(foo_pointer) == 1
        module.retain(foo_pointer)
        assert module.get_refcount_of(foo_pointer) == 2
        module.release(foo_pointer)
        assert module.get_refcount_of(foo_pointer) == 1

    def test_release_on_del(self, from_code):
        module = from_code("""
        export class Foo { constructor(public x: i32) {} }        
        export function collect(): void { gc.collect() }
        """)

        foo = module.Foo(5)
        foo_pointer = module.get_pointer(foo)
        assert module.get_refcount_of(foo_pointer) == 1

        # Trigger a delete
        del foo

        # Note: This seems to be the expected behaviour. The memory gets marked as cleared, but
        # the compiler does not waste effort to set the ref count to 0.
        assert module.get_refcount_of(foo_pointer) == 1

        # However, by creating a new object we can verify that it will be put in the same place
        # as the now deleted on.
        bar = module.Foo(9)
        bar_pointer = module.get_pointer(bar)
        assert bar_pointer == foo_pointer


def test_pass_objects_as_arguments(from_code):
    module = from_code("""
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
    """)

    file = module.File()

    assert file.addLine(module.Line("line 1")) == 1
    assert file.addLine(module.Line("line 2")) == 2