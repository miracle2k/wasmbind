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
