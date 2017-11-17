from ethereum import utils
from ethereum.transactions import Transaction
from ethereum.transaction_queue import TransactionQueue

from sharding import testing_lang
from sharding.tools import tester
from sharding.visualization import ShardingVisualization

def test_visualization():
    tl = testing_lang.TestingLang()
    cmds = """
        D0
        B5
        W0
        D0
        R0
        R0
        B25 #6
        C0
        R0
        R0
        B5 #7
        RC0
        C0
        R0
        B5 #8
        RC1
        C0,0,0
        B5 #9
        RC2
        C0,1,0
        R0
        B5 #10
        C0,1,1
        B5 #11
        C0
        B5 #12
        IC0,0,0
        B5 #13
        IC0,1,1
        B5 #14
        C1
        B5 #15
        RC3
        C0,2,1
        B5 #16
        C0,3,1
        B5 #17
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
        B5
    """

    tl.execute(cmds)

    # from sharding import used_receipt_store_utils
    # from sharding.tools import tester
    # shard_id = 0
    # urs = tester.ABIContract(tl.c, used_receipt_store_utils.get_urs_ct(shard_id), used_receipt_store_utils.get_urs_contract(shard_id)['addr'])
    # def watcher(log):
    #     print("!@# log_listeners watcher!!!")
    # # tl.c.chain.shards[shard_id].state.log_listeners.append(watcher)
    # # tl.c.shard_head_state[shard_id].log_listeners.append(watcher)
    # # urs.add_used_receipt(3)
    # # tl.execute("""C0
    # # B5""")
    # # tl.execute("""C0
    # # B5""")
    # print('!@# log_listeners head_state in tl:', len(tl.c.shard_head_state[shard_id].log_listeners))
    # print('!@# log_listeners state in tl:', len(tl.c.chain.shards[shard_id].state.log_listeners))

    sv = ShardingVisualization('period', tl.c, draw_in_period=True, show_events=True)
    sv.draw()
