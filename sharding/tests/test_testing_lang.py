from ethereum import utils

from sharding.testing_lang import TestingLang
from sharding.tools import tester


def test_testing_lang_general():
    tl = TestingLang()
    cmds = """
        D0 # deposit validator 0
        W0 # withdraw validator 0
        D0
        B25
        C0
        B5
        C0
        B5
        C0
        B5
        C0
        B5
        C0
        B5
        C0
        B5
        C0
        B5
        C0,0,0
        B5
        C0,1,0
        C1,0,0
#####   C2,1,0  # Error: no corresponding parent
    """
    tl.execute(cmds)

    chain = tl.get_tester_chain().chain
    assert tl.shard_head[0].header.hash == chain.shards[0].head.header.hash
    # tl.print_collations_level_order(0)


def test_testing_lang_comment():
    tl1 = TestingLang()
    cmd1 = """
        D0
        B25
        C0
        C1
        # C0
######### C1
    """
    tl1.execute(cmd1)
    tl2 = TestingLang()
    cmd2 = """
        D0
        B25
        C0
        C1
    """
    tl2.execute(cmd2)
    chain1 = tl1.get_tester_chain().chain
    chain2 = tl2.get_tester_chain().chain
    assert chain1.shards[0].head.header.hash == chain2.shards[0].head.header.hash
    assert chain1.shards[1].head.header.hash == chain2.shards[1].head.header.hash


def test_testing_lang_shard_head():
    tl = TestingLang()
    cmd = """
        D0
        B25
        C0
        B5
    """
    tl.execute(cmd)
    chain = tl.get_tester_chain().chain
    head_hash_10 = chain.shards[0].head.header.hash
    tl.execute("""
        C0,0,0
        B5
    """)
    assert head_hash_10 == chain.shards[0].head.header.hash
    assert tl.shard_head[0].header.hash == chain.shards[0].head.header.hash
    head_hash_11 = chain.shards[0].head.header.hash
    # head change
    tl.execute("""
        C0,1,1
        B5
    """)
    assert head_hash_10 != chain.shards[0].head.header.hash
    assert head_hash_11 == chain.shards[0].head.header.parent_collation_hash
    assert tl.shard_head[0].header.hash == chain.shards[0].head.header.hash
    assert tl.shard_head[0].header.parent_collation_hash == head_hash_11


def test_testing_lang_mk_transaction():
    tl = TestingLang()
    cmd = """
        D0
        B25
        C0
        B5
    """
    tl.execute(cmd)
    prev_balance = tl.c.head_state.get_balance(tester.accounts[1])
    tl.execute("T,0,1")
    assert (tl.c.head_state.get_balance(tester.accounts[1]) - prev_balance) == utils.denoms.gwei
    prev_balance = tl.c.shard_head_state[0].get_balance(tester.accounts[2])
    tl.execute("T0,1,2")
    assert (tl.c.shard_head_state[0].get_balance(tester.accounts[2]) - prev_balance) == \
           utils.denoms.gwei
    prev_balance = tl.c.shard_head_state[0].get_balance(tester.accounts[2])
    tl.execute("T,0,1,2")
    assert tl.c.shard_head_state[0].get_balance(tester.accounts[2]) == \
           (prev_balance + utils.denoms.gwei - 21000 * tester.GASPRICE)
