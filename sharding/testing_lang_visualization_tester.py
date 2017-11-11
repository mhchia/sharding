from ethereum import utils
from ethereum.transactions import Transaction
from ethereum.transaction_queue import TransactionQueue

from sharding import testing_lang
from sharding.tools import tester
from sharding.visualization import ShardingVisualization

_current_tester_chain = None

def get_current_tester_chain():
    global _current_tester_chain
    return _current_tester_chain


def set_current_tester_chain(c):
    global _current_tester_chain
    _current_tester_chain = c


def test_visualization():
    tl = testing_lang.TestingLang()
    cmds = """
        D0
        W0
        D0
        B25
        C0
        R0
        R0
        B5
        RC0
        C0
        R0
        B5
        RC1
        C0,0,0
        B5
        RC2
        C0,1,0
        R0
        B5
        C0,1,1
        B5
        C0
        B5
        IC0,0,0
        B5
        IC0,1,1
        B5
        C1
        B5
        RC3
        C0,2,1
        B5
        C0,3,1
        B5
    """
    cmd = """
        D0
        B25
        C0
        B5
        R0
        R0
        IC0,0,0
        B5
        RC0
        RC1
        C0
        B1
    """

    set_current_tester_chain(tl.c)
    tl.execute(cmds)

    record = tl.record
    sv = ShardingVisualization(record, tl.c.chain)
    sv.draw()
