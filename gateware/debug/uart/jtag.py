from migen.fhdl.std import *
from migen.genlib.record import Record
from migen.flow.actor import Sink, Source
from migen.genlib.resetsync import AsyncResetSynchronizer


jtag_layout = [
    ("tdi", 1),
    ("tdo", 1),
    ("clk", 1),
    ("shift", 1),
    ("rst", 1),
    ("capture", 1),
]


class BscanSpartan6(Module):
    def __init__(self, chain=1):
        self.jtag = Record(jtag_layout)
        # * BSCAN_SPARTAN6 outputs except TDI are all synchronous
        #   to falling TCK edges
        # * TDO is _synchronized_ to falling edges
        # * TDI must be sampled on rising edges
        # * use rising TCK as clock and keep in mind that there is
        #   always one cycle of latency TDI-to-TDO
        self.clk = Signal()
        # self.specials += Instance("BUFG", i_I=self.clk, o_O=self.jtag.clk)
        self.comb += self.jtag.clk.eq(self.clk)
        self.specials += Instance(
            "BSCAN_SPARTAN6", p_JTAG_CHAIN=chain,
            o_RESET=self.jtag.rst, o_CAPTURE=self.jtag.capture,
            o_TCK=self.clk, o_TDI=self.jtag.tdi, i_TDO=self.jtag.tdo,
            o_SHIFT=self.jtag.shift)


class Phy(Module):
    def __init__(self, impl, width=8):
        self.source = Source([("data", width)])
        self.sink = Sink([("data", width)])

        ###

        self.submodules.impl = impl
        jtag = impl.jtag
        self.clock_domains.cd_jtag = ClockDomain()
        self.specials += AsyncResetSynchronizer(self.cd_jtag,
                                                ResetSignal("sys"))
        reg = Signal(width + 1)

        # wire format:
        # target perspective
        # 10 bits
        # lsb first
        #
        # rx (host to target):
        # 0x001 # tx ack
        # 0x1fe # rx data byte mask
        # 0x200 # rx stb
        #
        # tx (target to host):
        # 0x001 # rx ack
        # 0x1fe # tx data byte mask
        # 0x200 # tx stb

        bit = Signal(max=width + 2)
        self.comb += [
            self.cd_jtag.clk.eq(jtag.clk),
            jtag.tdo.eq(Mux(bit == 0, self.source.ack, reg[0])),
            self.sink.ack.eq(jtag.tdi & jtag.shift & (bit == 0)),
            self.source.stb.eq(jtag.tdi & jtag.shift & (bit == width + 1)),
            self.source.data.eq(reg[1:]),
        ]
        self.sync.jtag += [
            If(jtag.rst | jtag.capture,
                bit.eq(0),
            ),
            If(jtag.shift,
                bit.eq(bit + 1),
                reg.eq(Cat(reg[1:], jtag.tdi)),
                If(bit == width + 1,
                    bit.eq(0),
                ),
                If(bit == 0,
                    reg.eq(Cat(self.sink.data, self.sink.stb)),
                ),
            ),
        ]
