from amaranth import *
from enum import IntEnum

DEFAULT_XLEN = 64

class AluOp(IntEnum):
    ADD = 0

class Alu(Elaboratable):
    def __init__(self, xlen=DEFAULT_XLEN):
        # Inputs
        self.en = Signal(name='alu_en')
        self.op = Signal(AluOp, name='alu_op')
        self.in1 = Signal(xlen, name='alu_in1')
        self.in2 = Signal(xlen, name='alu_in2')

        # Outputs
        self.out = Signal(xlen, name='alu_out')

    def elaborate(self, _):
        m = Module()

        with m.If(self.en):
            with m.Switch(self.op):
                with m.Case(AluOp.ADD):
                    m.d.comb += self.out.eq(self.in1 + self.in2)

        return m

class RegisterFile(Elaboratable):
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

        self.dbgout = Signal(xlen)

    def elaborate(self, _):
        m = Module()

        with m.Switch(self.sel1):
            with m.Case(0):
                # TODO: Optimize away in decoder
                m.d.comb += self.out1.eq(0)
            with m.Default():
                m.d.comb += self.out1.eq(self.regs[self.sel1 - 1])

        with m.Switch(self.sel2):
            with m.Case(0):
                m.d.comb += self.out2.eq(0)
            with m.Default():
                m.d.comb += self.out2.eq(self.regs[self.sel2 - 1])

        with m.If(self.wren):
            # TODO: Optimize x0 check away in decoder
            with m.If((self.wrsel > 0) & (self.wrsel < 31)):
                m.d.comb += self.regs[self.wrsel - 1].eq(self.wrval)

        return m

class BootRom(Elaboratable):
    def __init__(self, xlen=DEFAULT_XLEN):
        # State
        data = [
            0x0000_0533, # 0000_0000:  add  a0, x0, x0
            0x0420_0593, # 0000_0004:  addi a1, x0, 0x42   (aka: li a1, 0x42)
            0x00b5_0533, # 0000_0008:  add  a0, a0, a1
            0xffdf_f06f, # 0000_000c:  jal  x0, -4         (aka: j 0000_0008)
        ]

        self.mem = Memory(width=32, depth=len(data), init=data)

        # Inputs
        self.addr = Signal(xlen)

        # Outputs
        self.out = Signal(32)

    def elaborate(self, _):
        m = Module()

        with m.If(self.addr[2:] < self.mem.depth):
            m.d.comb += self.out.eq(self.mem[self.addr[2:]])

        return m

class Opcode(IntEnum):
    REG  = 0b0110011 # Register-only inst
    IMM  = 0b0010011 # Immediate inst
    JAL  = 0b1101111
    JARL = 0b1100111

class Funct3(IntEnum):
    IMM_ADDI = 0b000

class Funct7(IntEnum):
    REG_ADD  = 0b000_0000

class InstructionDecoder(Elaboratable):
    def __init__(self, alu, regs, xlen=DEFAULT_XLEN):
        # Links
        self.alu = alu
        self.regs = regs

        # Inputs
        self.inst = Signal(32)

        # Outputs
        self.illegal = Signal()
        self.alu_en = Signal()
        self.rd = Signal(5)
        self.pc_offset = Signal(signed(21))
        self.regwrite = Signal()

    def elaborate(self, _):
        m = Module()

        #
        #    | 32        25 | 24   20 | 19   15 | 14  12 | 11   7 | 6          0 |
        #    +--------------+---------+---------+--------+--------+--------------+
        #  R |    funct7    |   rs2   |   rs1   | funct3 |   rd   |    opcode    |
        #    +--------------+---------+---------+--------+--------+--------------+
        #  I |        imm[11:0]       |   rs1   | funct3 |   rd   |    opcode    |
        #    +------------------------+---------+--------+--------+--------------+
        #
        #    |    31   | 30         21 |    20   | 30       21  | 11   7 | 6          0 |
        #    +---------+---------------+---------+--------------+--------+--------------+
        #  J | imm[20] |   imm[10:1]   | imm[11] |  imm[19:12]  |   rd   |    opcode    |
        #    +-------------------------+---------+--------------+--------+--------------+
        #

        op = Signal(Opcode)
        rs1 = Signal(5)
        rs2 = Signal(5)
        funct3 = Signal(Funct3)
        funct7 = Signal(Funct7)
        i_imm = Signal(12)
        j_imm = Signal(20)

        m.d.comb += [
            # Decode instruction elements
            op.eq(self.inst[:7]),
            rs1.eq(self.inst[15:20]),
            self.rd.eq(self.inst[7:12]),

            # Always set rs1 contents as ALU in1
            self.regs.sel1.eq(rs1),
            self.alu.in1.eq(self.regs.out1),
        ]

        with m.Switch(op):
            with m.Case(Opcode.REG):
                m.d.comb += [
                    funct7.eq(self.inst[25:32]),
                    rs2.eq(self.inst[20:25]),
                    self.regwrite.eq(1),
                ]

                with m.Switch(funct7):
                    with m.Case(Funct7.REG_ADD): # add rd, rs1, rs2
                        m.d.comb += [
                            self.regs.sel2.eq(rs2),
                            self.alu.in2.eq(self.regs.out2),
                            self.alu.op.eq(AluOp.ADD),
                            self.alu_en.eq(1),
                        ]

                    with m.Default():
                        m.d.comb += self.illegal.eq(1)

            with m.Case(Opcode.IMM):
                m.d.comb += [
                    funct3.eq(self.inst[12:15]),
                    i_imm.eq(self.inst[20:32]),
                    self.regwrite.eq(1),
                ]

                with m.Switch(funct3):
                    with m.Case(Funct3.IMM_ADDI): # addi rd, rs1, <imm>
                        m.d.comb += [
                            self.alu.in2.eq(i_imm),
                            self.alu.op.eq(AluOp.ADD),
                            self.alu_en.eq(1),
                        ]

                    with m.Default():
                        m.d.comb += self.illegal.eq(1)

            with m.Case(Opcode.JAL):              # jal rd, <imm>
                with m.If(self.rd > 0):
                    m.d.comb += [
                        self.regwrite.eq(1),

                        # HACK: The old PC is pass-thru'd the ALU to ease
                        # the REGWRITE stage for now
                        self.alu.in1.eq(self.regs.pc),
                        self.alu.in2.eq(0),
                        self.alu.op.eq(AluOp.ADD),
                        self.alu_en.eq(1),
                    ]

                m.d.comb += [
                    # Decode offset directly into pc_offset wire
                    # The first bit is intentionally left zero, the JAL
                    # immediate must be shifted left by 1 anyways
                    # An additional `2` is subtracted here from the unshifted
                    # value to counter the early PC increment done in the
                    # FETCH stage.
                    self.pc_offset[1:11].eq(self.inst[21:31] - 2),
                    self.pc_offset[11].eq(self.inst[20]),
                    self.pc_offset[12:20].eq(self.inst[12:20]),
                    self.pc_offset[20].eq(self.inst[31]),
                ]

            with m.Default():
                m.d.comb += self.illegal.eq(1)

        return m

class PipelineStage(IntEnum):
    FETCH = 0
    DECODE = 1
    MEMACCESS = 2
    EXECUTE = 3
    WRITEBACK = 4

class Cpu(Elaboratable):
    def __init__(self, xlen=DEFAULT_XLEN):
        self.cycles = Signal(xlen)
        self.stage = Signal(PipelineStage)
        self.halt = Signal()

    def elaborate(self, _):
        m = Module()

        alu = m.submodules.alu = Alu()
        bootrom = m.submodules.bootrom = BootRom()
        regs = m.submodules.regs = RegisterFile()
        dec = m.submodules.dec = InstructionDecoder(alu, regs)

        with m.If(~self.halt):
            with m.Switch(self.stage):
                with m.Case(PipelineStage.FETCH):
                    m.d.comb += [
                        # Reset possibly-modifiying state
                        regs.wren.eq(0),

                        # Read instruction from BootROM and feed into decoder
                        bootrom.addr.eq(regs.pc),
                    ]

                    m.d.sync += [
                        # Feed fetched instruction into decoder
                        dec.inst.eq(bootrom.out),

                        # Increment PC
                        regs.pc.eq(regs.pc + 4),
                    ]

                with m.Case(PipelineStage.DECODE):
                    # Fully halt in case an illegal instruction is encountered
                    m.d.sync += self.halt.eq(dec.illegal)

                with m.Case(PipelineStage.MEMACCESS):
                    pass

                with m.Case(PipelineStage.EXECUTE):
                    m.d.sync += [
                        alu.en.eq(dec.alu_en),
                        regs.pc.eq(regs.pc + Mux(dec.pc_offset != 0, dec.pc_offset - 4, 0)),
                    ]

                with m.Case(PipelineStage.WRITEBACK):
                    m.d.sync += alu.en.eq(0)

                    with m.If(dec.regwrite):
                        m.d.comb += [
                            regs.wrsel.eq(dec.rd),
                            regs.wrval.eq(alu.out),
                            regs.wren.eq(1),
                        ]

            with m.If(self.stage == PipelineStage.WRITEBACK):
                m.d.sync += [
                    self.stage.eq(PipelineStage.FETCH),
                    self.cycles.eq(self.cycles + 1),
                ]
            with m.Else():
                m.d.sync += self.stage.eq(self.stage + 1)

        return m
