from amaranth import *
from enum import IntEnum

DEFAULT_XLEN = 64

class AluOp(IntEnum):
    ADD = 0

class Alu(Elaboratable):
    def __init__(self, xlen=DEFAULT_XLEN):
        # Inputs
        self.en = Signal()
        self.op = Signal(range(len(AluOp)))
        self.in1 = Signal(xlen)
        self.in2 = Signal(xlen)

        # Outputs
        self.out = Signal(xlen)

    def elaborate(self, _):
        m = Module()

        with m.If(self.en == 1):
            with m.Switch(self.op):
                with m.Case(AluOp.ADD):
                    m.d.comb += self.out.eq(self.in1 + self.in2)

        return m

class Registeregf(Elaboratable):
    def __init__(self, xlen=DEFAULT_XLEN):
        # State
        self.regs = Array([Signal(xlen)] * 30) # x1 - x31
        self.pc = Signal(xlen) # x32

        # Inputs
        self.sel1 = Signal(5)
        self.sel2 = Signal(5)
        self.wren = Signal()
        self.wrsel = Signal(5)
        self.wrval = Signal(xlen)

        # Outputs
        self.out1 = Signal(xlen)
        self.out2 = Signal(xlen)

    def elaborate(self, _):
        m = Module()

        with m.Switch(self.sel1):
            with m.Case(0):
                # TODO: Optimize away everywhere else
                m.d.comb += self.out1.eq(0)
            with m.Default():
                m.d.comb += self.out1.eq(self.regs[self.sel1 - 1])

        with m.Switch(self.sel2):
            with m.Case(0):
                m.d.comb += self.out2.eq(0)
            with m.Default():
                m.d.comb += self.out2.eq(self.regs[self.sel2 - 1])

        with m.If(self.wren == 1):
            # TODO: Eliminate need for checking for x0
            with m.If((self.wrsel > 0) & (self.wrsel < 31)):
                m.d.comb += self.regs[self.wrsel - 1].eq(self.wrval)

        return m

class BootRom(Elaboratable):
    def __init__(self, xlen=DEFAULT_XLEN):
        # Inputs
        self.addr = Signal(xlen)

        # Outputs
        self.out = Signal(xlen)

        # State
        data = [
            0x0000_0533, # add  a0, x0, x0
            0x0420_0593, # addi a1, x0, 0x42   (aka li a1, 0x42)
            0x00b5_0533, # add  a0, a0, a1
        ]

        self.mem = Memory(width=xlen, depth=len(data), init=data)

    def elaborate(self, _):
        m = Module()

        with m.If(self.addr[2:] < self.mem.depth):
            m.d.comb += self.out.eq(self.mem[self.addr[2:]])

        return m

class Opcode(IntEnum):
    REG = 0b0110011 # Register-only inst
    IMM = 0b0010011 # Immediate inst

class Funct3(IntEnum):
    IMM_ADDI = 0b000

class Funct7(IntEnum):
    REG_ADD  = 0b000_0000

class InstructionDecoder(Elaboratable):
    def __init__(self, alu, regf, xlen=DEFAULT_XLEN):
        # Links
        self.alu = alu
        self.regf = regf

        # Inputs
        self.inst = Signal(xlen)

        # Outputs
        self.illegal = Signal()
        self.alu_en = Signal()
        self.rd = Signal(5)
        self.regwrite = Signal()

    def elaborate(self, _):
        m = Module()

        #
        #    | 32        25 | 24   20 | 19   15 | 14  12 | 11   7 | 6          0 |
        #    +--------------+---------+---------+--------+--------+--------------+
        #  R |    funct7    |   rs2   |   rs1   | funct3 |   rd   |    opcode    |
        #    +--------------+---------+---------+--------+--------+--------------+
        #  I |    immediate [11:0]    |   rs1   | funct3 |   rd   |    opcode    |
        #    +------------------------+---------+--------+--------+--------------+
        #
        #

        op = Signal(7)
        rs1 = Signal(5)
        rs2 = Signal(5)
        funct3 = Signal(3)
        funct7 = Signal(7)
        imm = Signal(12)

        m.d.comb += [
            op.eq(self.inst[:7]),
            rs1.eq(self.inst[15:20]),
            rs2.eq(self.inst[20:25]),
            funct3.eq(self.inst[12:15]),
            funct7.eq(self.inst[25:32]),
            imm.eq(self.inst[20:32]),
            self.regf.sel1.eq(rs1),
            self.alu.in1.eq(self.regf.out1),
            self.rd.eq(self.inst[7:12]),
        ]

        with m.Switch(op):
            with m.Case(Opcode.REG):
                m.d.comb += self.regwrite.eq(1);

                with m.Switch(funct7):
                    with m.Case(Funct7.REG_ADD): # add rd, rs1, rs2
                        m.d.comb += [
                            self.regf.sel2.eq(rs2),
                            self.alu.in2.eq(self.regf.out2),
                            self.alu.op.eq(AluOp.ADD),
                            self.alu_en.eq(1),
                        ]

                    with m.Default():
                        m.d.comb += self.illegal.eq(1)

            with m.Case(Opcode.IMM):
                m.d.comb += self.regwrite.eq(1);

                with m.Switch(funct3):
                    with m.Case(Funct3.IMM_ADDI):
                        m.d.comb += [
                            self.alu.in2.eq(imm),
                            self.alu.op.eq(AluOp.ADD),
                            self.alu_en.eq(1),
                        ]

                    with m.Default():
                        m.d.comb += self.illegal.eq(1)

            with m.Default():
                m.d.comb += self.illegal.eq(1)

        return m

class PipelineStage(IntEnum):
    FETCH = 0
    DECODE = 1
    EXECUTE = 2
    MEMACCESS = 3
    REGWRITE = 4

class Cpu(Elaboratable):
    def __init__(self, xlen=DEFAULT_XLEN):
        self.cycles = Signal(xlen)
        self.stage = Signal(range(len(PipelineStage)))
        self.halt = Signal()

    def elaborate(self, platform):
        m = Module()

        alu = m.submodules.alu = Alu()
        bootrom = m.submodules.bootrom = BootRom()
        regf = m.submodules.regf = Registeregf()
        dec = m.submodules.dec = InstructionDecoder(alu, regf)

        with m.If(self.halt == 0):
            with m.Switch(self.stage):
                with m.Case(PipelineStage.FETCH):
                    m.d.sync += [
                        # Reset possibly-modifiying state
                        alu.en.eq(0),
                        regf.wren.eq(0),

                        regf.pc.eq(regf.pc + 4),
                        bootrom.addr.eq(regf.pc),
                        dec.inst.eq(bootrom.out),
                    ]

                with m.Case(PipelineStage.DECODE):
                    # Fully halt in case there an illegal instruction is encountered
                    m.d.sync += self.halt.eq(dec.illegal)

                with m.Case(PipelineStage.EXECUTE):
                    m.d.sync += [
                        alu.en.eq(dec.alu_en),
                    ]

                with m.Case(PipelineStage.MEMACCESS):
                    m.d.sync += [
                        # alu.en.eq(0),
                    ]

                with m.Case(PipelineStage.REGWRITE):
                    with m.If(dec.regwrite):
                        m.d.sync += [
                            regf.wrsel.eq(dec.rd),
                            regf.wrval.eq(alu.out),
                            regf.wren.eq(1),
                        ]

            with m.If(self.stage == PipelineStage.REGWRITE):
                m.d.sync += [
                    self.stage.eq(PipelineStage.FETCH),
                    self.cycles.eq(self.cycles + 1),
                ]
            with m.Else():
                m.d.sync += self.stage.eq(self.stage + 1)

        return m
