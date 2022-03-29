from amaranth import *
from amaranth.sim import *
from . import Cpu, PipelineStage

def start():
    cpu = Cpu()

    def process():
        # Run for 10 cycles
        for _ in range(10 * len(PipelineStage)):
            yield

    sim = Simulator(cpu)
    sim.add_clock(1e-6) # 1 MHz
    sim.add_sync_process(process)

    with sim.write_vcd("teuthida.vcd", "teuthida.gtkw"):
        sim.run()
