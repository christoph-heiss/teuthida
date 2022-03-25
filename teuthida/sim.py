from amaranth import *
from nmigen.back.pysim import Simulator, Delay, Settle

def process():
    yield

def start():
    m = Module()
    sim = Simulator(m)
    sim.add_clock(1e-6) # 1 MHz
    sim.add_process(process)

    sim.run()
