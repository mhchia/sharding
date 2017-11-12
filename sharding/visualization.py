from collections import defaultdict
import re

import graphviz as gv


GENESIS_HASH = b'\x00' * 32
LABEL_BLOCK = 'B'
LABEL_INVALID_COLLATION = 'IC'
LABEL_COLLATION = 'C'
LABEL_DEPOSIT = 'D'
LABEL_RECEIPT = 'R'
LABEL_RECEIPT_CONSUMING = 'RC'
LABEL_TRANSACTION = 'T'
LABEL_WITHDRAW = 'W'
LABEL_ADD_HEADER = 'AH'
LEN_HASH = 8


def get_collation_hash(collation):
    if collation is None:
        return GENESIS_HASH
    return collation.header.hash


def get_shorten_hash(hash_bytes32):
    # TODO: work around
    return hash_bytes32.hex()[:LEN_HASH]


class Record(object):

    def __init__(self):
        self.collations = defaultdict(dict)
        # 'label' -> 'node_name'
        self.tx_label_node_map = {}
        # 'hash:label' -> previous 'hash:label'
        self.node_label_map = {}
        # [{'shard_id', 'startgas', 'gasprice', 'to', 'value', 'data'}, ...]
        self.receipts = []

        self.node_events = defaultdict(list)

        self.blocks = {}
        self.mainchain_head = None

        self.collation_map = {}
        # collation_hash -> (height, order)
        self.collation_coordinate = {}
        self.shard_head = {}
        self.collation_validity = {}


    def add_block(self, block):
        self.blocks[block.header.hash] = block
        if self.mainchain_head is None or self.mainchain_head.header.number < block.header.number:
            self.mainchain_head = block


    def add_collation_old(self, collation):
        collation_hash = get_collation_hash(collation)
        self.collations[collation.header.shard_id][collation_hash] = collation


    def mk_event_label(self, label, number):
        return "{}{}".format(label, number)


    def add_event_by_node(self, node_hash, event, number):
        label = self.mk_event_label(event, number)
        self.tx_label_node_map[label] = node_hash
        prev_label = self.get_prev_label(label)
        if prev_label is not None:
            prev_label_node_hash = self.tx_label_node_map[prev_label]
            index = get_shorten_hash(node_hash) + ':' + label
            value = get_shorten_hash(prev_label_node_hash) + ':' + prev_label
            self.node_label_map[index] = value
        self.node_events[node_hash].append(label)


    def add_add_header_by_node(self, node_hash, number):
        self.add_event_by_node(node_hash, LABEL_ADD_HEADER, number)


    def add_deposit_by_node(self, node_hash, number):
        self.add_event_by_node(node_hash, LABEL_DEPOSIT, number)


    def add_withdraw_by_node(self, node_hash, number):
        self.add_event_by_node(node_hash, LABEL_WITHDRAW, number)


    def add_receipt_by_node(self, node_hash, number):
        self.add_event_by_node(node_hash, LABEL_RECEIPT, number)


    def add_receipt_consuming_by_node(self, node_hash, number):
        self.add_event_by_node(node_hash, LABEL_RECEIPT_CONSUMING, number)


    def get_tx_labels_from_node(self, node_hash):
        return self.node_events[node_hash]


    def _divide_label(self, label):
        cmd_params_pat = re.compile(r"([A-Za-z]+)([0-9,]+)")
        cmd, params = cmd_params_pat.match(label).groups()
        if (cmd + params) != label:
            raise ValueError("Bad token")
        return cmd, params


    def get_prev_label(self, label):
        cmd, param = self._divide_label(label)
        if cmd == LABEL_WITHDRAW:
            prev_cmd = LABEL_DEPOSIT
        elif cmd == LABEL_RECEIPT_CONSUMING:
            prev_cmd = LABEL_RECEIPT
        else:
            return None
        return prev_cmd + param


    def add_collation(self, collation, is_valid=True):
        parent_collation_hash = collation.header.parent_collation_hash
        parent_height, parent_kth = self.collation_coordinate[parent_collation_hash]
        shard_id = collation.header.shard_id
        shard_collation_map = self.collation_map[shard_id]
        insert_index = 0
        try:
            layer_at_height = shard_collation_map[parent_height + 1]
            while insert_index < len(layer_at_height):
                node = layer_at_height[insert_index]
                node_parent_hash = node.header.parent_collation_hash
                node_height, node_parent_kth = self.collation_coordinate[node_parent_hash]
                if node_parent_kth > parent_kth:
                    break
                insert_index += 1
        except IndexError:
            layer_at_height = []
            shard_collation_map.append(layer_at_height)

        layer_at_height.insert(insert_index, collation)

        collation_hash = get_collation_hash(collation)
        # if it is the longest chain, set it as the shard head
        if is_valid and (len(layer_at_height) == 1):
            self.shard_head[shard_id] = collation

        self.add_collation_old(collation)
        self.collation_validity[collation_hash] = is_valid
        self.collation_coordinate[collation_hash] = (parent_height + 1, insert_index)


    def set_collation_invalid(self, collation_hash):
        self.collation_validity[collation_hash] = False


    def init_shard(self, shard_id):
        self.collation_map[shard_id] = [[None]]
        self.collation_coordinate[GENESIS_HASH] = (0, 0)


    def get_shard_head_hash(self, shard_id):
        return get_collation_hash(self.shard_head[shard_id])


    def get_collation_hash_by_coordinate(self, shard_id, parent_kth, parent_height):
        collation = self.collation_map[shard_id][parent_height][parent_kth]
        return get_collation_hash(collation)


    def get_collation_coordinate_by_hash(self, collation_hash):
        return self.collation_coordinate[collation_hash]


    def is_collation_valid(self, collation_hash):
        return self.collation_validity[collation_hash]


class ShardingVisualization(object):

    NUM_TX_IN_BLOCK = 3
    EMPTY_TX = '&nbsp;' * 4
    GENESIS_HASH = b'\x00' * 32

    def __init__(self, filename, tester_chain, draw_in_period=False):
        self.record = tester_chain.record
        self.mainchain = tester_chain.chain
        self.draw_in_period = draw_in_period
        self.min_hash = None
        self.mainchain_caption = "mainchain" if not draw_in_period else "period"
        # FIXME: workaround
        self.block_shorten_hash_to_period = {}

        self.layers = {}
        self.g = gv.Digraph('G', filename=filename)


    def draw_event_edge(self, node, prev_node):
        self.g.edge(node, prev_node, style='dashed', constraint='false')


    def draw_block(self, prev_hash, current_hash, txs, height):
        if self.draw_in_period:
            caption = '{}'.format(height)
        else:
            caption = 'B{}: {}'.format(height, current_hash)
        self.draw_struct(prev_hash, current_hash, height, txs, 'record', caption)


    def draw_collation(self, prev_hash, current_hash, height, order, txs, is_valid=True):
        caption = 'C' if is_valid else 'IC'
        caption += '({}, {}): {}'.format(height, order, current_hash)
        self.draw_struct(prev_hash, current_hash, height, txs, 'Mrecord', caption)
        if not is_valid:
            self.g.node(current_hash, color='red', style='filled')


    def draw_struct(self, prev_hash, current_hash, height, txs, shape, caption):
        # assert len(txs) <= self.NUM_TX_IN_BLOCK
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
            if self.draw_in_period and current_hash in self.block_shorten_hash_to_period.keys():
                label_index = self.block_shorten_hash_to_period[current_hash] + ':' + label
            try:
                prev_label_index = self.record.node_label_map[label_index]
                prev_hash, prev_label = prev_label_index.split(':')
                if self.draw_in_period and prev_hash in self.block_shorten_hash_to_period.keys():
                    prev_label_index = self.block_shorten_hash_to_period[prev_hash] + ':' + prev_label
                self.draw_event_edge(label_index, prev_label_index)
            except:
                pass


    def draw_mainchain(self, chain):
        current_block = chain.head
        self.min_hash = get_shorten_hash(current_block.header.hash)

        self.g.node(self.mainchain_caption, shape='none')
        self.layers[self.mainchain_caption] = []

        tx_labels_in_current_period = []
        # TODO: insert blocks into record, and then iterate them
        while current_block is not None:
            # draw head
            prev_block = chain.get_parent(current_block)
            current_period = current_block.header.number // chain.env.config['PERIOD_LENGTH']
            if current_period == 0:
                prev_period = self.mainchain_caption
            else:
                prev_period = current_period - 1
            if prev_block is None:
                prev_block_hash = self.mainchain_caption
            else:
                prev_block_hash = get_shorten_hash(prev_block.header.hash)
                self.block_shorten_hash_to_period[prev_block_hash] = str(prev_period)

            current_block_hash = get_shorten_hash(current_block.header.hash)
            self.block_shorten_hash_to_period[current_block_hash] = str(current_period)
            tx_labels = self.record.get_tx_labels_from_node(current_block.header.hash)
            tx_labels_in_current_period = tx_labels + tx_labels_in_current_period
            if not self.draw_in_period:
                self.draw_block(
                    prev_block_hash,
                    current_block_hash,
                    tx_labels,
                    current_block.header.number,
                )
                self.layers[current_block_hash] = []
            elif current_block.header.number % chain.env.config['PERIOD_LENGTH'] == 0:
                self.draw_block(
                    str(prev_period),
                    str(current_period),
                    tx_labels_in_current_period,
                    current_period,
                )
                tx_labels_in_current_period = []
                self.layers[str(current_period)] = []
            current_block = prev_block


    def draw_shardchains(self, record):
        for shard_id, collations in record.collations.items():
            shardchain_caption = "shard_" + str(shard_id)
            self.g.node(shardchain_caption, shape='none')
            self.layers[self.mainchain_caption].append(shardchain_caption)
            # TODO: first insert all collations into record and then iterate them
            collations = record.collations[shard_id]
            for collation_hash, collation in collations.items():
                if collation_hash == self.GENESIS_HASH:
                    continue
                height, order = self.record.get_collation_coordinate_by_hash(collation_hash)
                name = get_shorten_hash(collation_hash)
                prev_name = collation.header.parent_collation_hash
                if prev_name == self.GENESIS_HASH:
                    prev_name = shardchain_caption
                else:
                    prev_name = get_shorten_hash(prev_name)
                period_start_prevhash = get_shorten_hash(
                    collation.header.period_start_prevhash,
                )
                if self.draw_in_period:
                    self.layers[str(collation.header.expected_period_number)].append(name)
                else:
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
            elif period == self.mainchain_caption:
                rank = 'max'
            self.add_rank([period] + labels, rank)


    def draw(self):
        self.draw_mainchain(self.mainchain)
        self.draw_shardchains(self.record)
        print(self.layers)
        self.set_rank(self.layers)

        print(self.g.source)
        self.g.view()
