from amaranth.back import verilog
from . import Cpu

def gen_verilog():
    cpu = Cpu()

    with open('teuthida.v', 'w') as f:
        f.write(verilog.convert(cpu))

