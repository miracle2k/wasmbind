import pytest
import wasmer
import subprocess

from wasmbind import Module


@pytest.fixture
def from_code(tmpdir):
    def from_code(assemblyscript: str) -> Module:
        """
        Run "asc", the AssemblyScript compiler, load the wasm module, wrap it in a Module to test.

        TODO: It would be super cool if we could run the AssemblyScript compiler through WASM.
        """
        scriptfile = tmpdir.join('code.ts')
        scriptfile.write_text(assemblyscript, encoding='utf-8')

        process = subprocess.Popen(
            ['npx', '-q', 'assemblyscript', str(scriptfile), '-b', '--use', 'abort='],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out_bytes, err = process.communicate()
        if err:
            raise ValueError(err)
        module = wasmer.Module(out_bytes)

        instance = module.instantiate()
        return Module(instance)

    return from_code
