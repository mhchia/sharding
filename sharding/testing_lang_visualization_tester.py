import graphviz as gv

from ethereum import utils
from ethereum.transactions import Transaction
from ethereum.transaction_queue import TransactionQueue

from sharding import testing_lang
from sharding.tools import tester


class ShardingVisualization(object):

    NUM_TX_IN_BLOCK = 3
    EMPTY_TX = '&nbsp;' * 4
    GENESIS_HASH = b'\x00' * 32
    MAINCHAIN_CAPTION = "mainchain"

    def __init__(self, record, mainchain):
        self.record = record
        self.mainchain = mainchain
        self.min_hash = None

        self.layers = {}
        self.g = gv.Digraph('G', filename='image')


    def draw_event_edge(self, node, prev_node):
        self.g.edge(node, prev_node, style='dashed', constraint='false')


    def draw_block(self, prev_hash, current_hash, txs, height):
        caption = 'B{}: {}'.format(height, current_hash)
        self.draw_struct(prev_hash, current_hash, height, txs, 'record', caption)


    def draw_collation(self, prev_hash, current_hash, height, order, txs, is_valid=True):
        caption = 'C' if is_valid else 'IC'
        caption += '({}, {}): {}'.format(height, order, current_hash)
        self.draw_struct(prev_hash, current_hash, height, txs, 'Mrecord', caption)


    def draw_struct(self, prev_hash, current_hash, height, txs, shape, caption):
        assert len(txs) <= self.NUM_TX_IN_BLOCK
        assert isinstance(height, int)
        prev_label = '<prev> prev: \n {}'.format(prev_hash)
        txs_label = '{'
        for i in range(self.NUM_TX_IN_BLOCK):
            if i >= len(txs):
                txs_label += '<tx{}> '.format(i)
                txs_label += self.EMPTY_TX
            else:
                txs_label += '<{}> '.format(txs[i])
                txs_label += txs[i]
            if i != self.NUM_TX_IN_BLOCK - 1:
                txs_label += ' | '
        txs_label += '}'
        # label = '{ %s | %s | %s }' % (hash_label, txs_label, prev_label)
        if len(txs) != 0:
            label = '{ %s | %s }' % (caption, txs_label)
        else:
            label = '{ %s }' % caption
        self.g.node(current_hash, label, shape=shape)
        self.g.edge(current_hash, prev_hash) # , weight=weight)

        # draw event edges
        for label in txs:
            label_index = current_hash + ':' + label
            try:
                prev_label_index = self.record.node_label_map[label_index]
                self.draw_event_edge(label_index, prev_label_index)
            except:
                pass


    def draw_mainchain(self, chain):
        current_block = chain.head
        self.min_hash = testing_lang.get_shorten_hash(current_block.header.hash)

        self.g.node(self.MAINCHAIN_CAPTION, shape='none')
        self.layers[self.MAINCHAIN_CAPTION] = []

        while current_block is not None:
            # draw head
            prev_block = chain.get_parent(current_block)
            if prev_block is None:
                prev_block_hash = self.MAINCHAIN_CAPTION
            else:
                prev_block_hash = testing_lang.get_shorten_hash(prev_block.header.hash)
            current_block_hash = testing_lang.get_shorten_hash(current_block.header.hash)
            # print("!@# {}: {}".format(current_block.header.number, current_block_hash))
            tx_labels = self.record.get_tx_labels_from_node(current_block.header.hash)
            self.draw_block(
                prev_block_hash,
                current_block_hash,
                tx_labels,
                current_block.header.number,
            )
            self.layers[current_block_hash] = []
            current_block = prev_block


    def draw_shardchains(self, record):
        for shard_id, collations in record.collations.items():
            shardchain_caption = "shard_" + str(shard_id)
            self.g.node(shardchain_caption, shape='none')
            self.layers[self.MAINCHAIN_CAPTION].append(shardchain_caption)
            collations = record.collations[shard_id]
            for collation_hash, collation in collations.items():
                if collation_hash == self.GENESIS_HASH:
                    continue
                height, order = self.record.get_collation_coordinate_by_hash(collation_hash)
                name = testing_lang.get_shorten_hash(collation_hash)
                prev_name = collation.header.parent_collation_hash
                if prev_name == self.GENESIS_HASH:
                    prev_name = shardchain_caption
                else:
                    prev_name = testing_lang.get_shorten_hash(prev_name)
                period_start_prevhash = testing_lang.get_shorten_hash(
                    collation.header.period_start_prevhash,
                )
                self.layers[period_start_prevhash].append(name)
                # g.edge(name, prev_name)
                # g.node(name, label=label)#, shape='Mrecord')
                tx_labels = record.get_tx_labels_from_node(collation.header.hash)
                is_valid = self.record.is_collation_valid(collation_hash)
                self.draw_collation(prev_name, name, height, order, tx_labels, is_valid)


    def add_rank(self, node_list, rank='same'):
        rank_same_str = "\t{rank=%s; " % rank
        for node in node_list:
            rank_same_str += (self.g._quote(node) + '; ')
        rank_same_str += '}'
        self.g.body.append(rank_same_str)


    def set_rank(self, layers):
        # set rank
        for period, labels in layers.items():
            rank = 'same'
            if period == self.min_hash:
                rank = 'source'
            elif period == self.MAINCHAIN_CAPTION:
                rank = 'max'
            self.add_rank([period] + labels, rank)


    def draw(self):
        self.draw_mainchain(self.mainchain)
        self.draw_shardchains(self.record)
        self.set_rank(self.layers)

        print(self.g.source)
        self.g.view()


_current_state = None

def set_state(state):
    global _current_state
    if _current_state is None:
        _current_state = state


# [sha3("add_header()")], header)
# [sha3("add_header()"), sha3("change_head"), entire_header_hash], concat('', previous_head_hash))
add_header_topic = utils.sha3("add_header()")
# [sha3("deposit()"), as_bytes32(validation_code_addr)], concat('', as_bytes32(index))
deposit_topic = utils.sha3("deposit()")
# [sha3("withdraw")], concat('', as_bytes(validator_index))
withdraw_topic = utils.sha3("withdraw()")
# [sha3("tx_to_shard()"), as_bytes32(to), as_bytes32(shard_id)], as_bytes32(receipt_id)
receipt_topic = utils.sha3("tx_to_shard()")
# [sha3("add_used_receipt()")], concat('', as_bytes32(receipt_id))
receipt_consuming_topic = utils.sha3("add_used_receipt()")

add_header_events = []
change_head_events = []
deposit_events = []
withdraw_events = []
receipt_events = []
receipt_consuming_events = []

def add_header_watcher(log):
    if log.topics[0] == utils.big_endian_to_int(add_header_topic) and \
            len(log.topics) == 1:
        print("!@# watcher add_header=", log.data)


def change_head_watcher(log):
    if log.topics[0] == utils.big_endian_to_int(add_header_topic) and \
            len(log.topics) > 1 and \
            log.topics[1] == utils.big_endian_to_int(utils.sha3("change_head")):
        current_head_hash = hex(log.topics[2])[2:10]
        previous_head_hash = testing_lang.get_shorten_hash(log.data)
        print("!@# watcher change_head change_head={}, previous_head={}".format(current_head_hash, previous_head_hash))


def deposit_event_watcher(log):
    if log.topics[0] == utils.big_endian_to_int(deposit_topic):
        print("!@# watcher deposit")


def withdraw_event_watcher(log):
    if log.topics[0] == utils.big_endian_to_int(withdraw_topic):
        print("!@# watcher withdraw")


def receipt_event_watcher(log):
    if log.topics[0] == utils.big_endian_to_int(receipt_topic):
        print("!@# watcher receipt")


def receipt_consuming_event_watcher(log):
    if log.topics[0] == utils.big_endian_to_int(receipt_consuming_topic):
        print("!@# watcher receipt-consuming")


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
    watcher_list = [
        add_header_watcher,
        change_head_watcher,
        deposit_event_watcher,
        withdraw_event_watcher,
        receipt_event_watcher,
        receipt_consuming_event_watcher,
    ]
    tl.c.chain.state.log_listeners += watcher_list
    tl.execute(cmds)

    # g.attr(splines='polyline')
    # g.attr(nodesep='2')
    # g.attr(ranksep='2.0')

    record = tl.record
    sv = ShardingVisualization(record, tl.c.chain)
    sv.draw()
