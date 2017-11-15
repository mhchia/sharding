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

    TYPE_BLOCK = 0
    TYPE_COLLATION = 1

    def __init__(self):
        self.collations = defaultdict(dict)
        # 'label' -> 'node_name'
        self.tx_label_node_map = {}
        # 'hash:label' -> previous 'hash:label'
        self.node_label_map = {}
        # [{'shard_id', 'startgas', 'gasprice', 'to', 'value', 'data'}, ...]
        self.receipts = []

        self.node_type = {}
        # self.node_events = defaultdict(lambda: dict([('node_type', None), ('label_obj_list', [])]))
        self.node_events = defaultdict(list)

        self.blocks = {}
        self.mainchain_head_header = None
        self.mainchain_genesis_header = None

        self.collation_matrix = {}
        # collation_hash -> (height, order)
        self.collation_coordinate = {}
        self.shard_head = {}
        self.collation_validity = {}


    def add_block(self, block):
        header = block.header
        self.blocks[header.hash] = header
        if header.number == 0:
            self.mainchain_genesis_header = header
            print('!@# genesis={}'.format(header.hash))
        if self.mainchain_head_header is None or \
                self.mainchain_head_header.number < header.number:
            self.mainchain_head_header = header


    def mk_event_label(self, label, number):
        return "{}{}".format(label, number)


    def add_event_by_node(self, node_hash, event, number, node_type):
        label = self.mk_event_label(event, number)
        self.tx_label_node_map[label] = node_hash
        prev_label = self.get_prev_label(label)
        if prev_label is not None:
            prev_label_node_hash = self.tx_label_node_map[prev_label]
        else:
            prev_label_node_hash = None
        self.node_type[node_hash] = node_type
        obj = {
            'label': label,
            'prev_label': prev_label,
            'prev_label_node_hash': prev_label_node_hash,
        }
        self.node_events[node_hash].append(obj)


    def add_event_in_block(self, node_hash, event, number):
        self.add_event_by_node(node_hash, event, number, self.TYPE_BLOCK)


    def add_event_in_collation(self, node_hash, event, number):
        self.add_event_by_node(node_hash, event, number, self.TYPE_COLLATION)


    def add_add_header_by_node(self, node_hash, number):
        # self.add_event_in_block(node_hash, LABEL_ADD_HEADER, number)
        pass


    def add_deposit_by_node(self, node_hash, number):
        self.add_event_in_block(node_hash, LABEL_DEPOSIT, number)


    def add_withdraw_by_node(self, node_hash, number):
        self.add_event_in_block(node_hash, LABEL_WITHDRAW, number)


    def add_receipt_by_node(self, node_hash, number):
        self.add_event_in_block(node_hash, LABEL_RECEIPT, number)


    def add_receipt_consuming_by_node(self, node_hash, number):
        self.add_event_in_collation(node_hash, LABEL_RECEIPT_CONSUMING, number)


    def get_tx_labels_from_node(self, node_hash):
        if node_hash not in self.node_events:
            return []
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
        shard_collation_matrix = self.collation_matrix[shard_id]
        insert_index = 0
        try:
            layer_at_height = shard_collation_matrix[parent_height + 1]
            while insert_index < len(layer_at_height):
                node = layer_at_height[insert_index]
                node_parent_hash = node.header.parent_collation_hash
                node_height, node_parent_kth = self.collation_coordinate[node_parent_hash]
                if node_parent_kth > parent_kth:
                    break
                insert_index += 1
        except IndexError:
            layer_at_height = []
            shard_collation_matrix.append(layer_at_height)

        layer_at_height.insert(insert_index, collation)

        collation_hash = get_collation_hash(collation)
        # if it is the longest chain, set it as the shard head
        if is_valid and (len(layer_at_height) == 1):
            self.shard_head[shard_id] = collation

        self.collations[collation.header.shard_id][collation_hash] = collation
        self.collation_validity[collation_hash] = is_valid
        self.collation_coordinate[collation_hash] = (parent_height + 1, insert_index)


    def set_collation_invalid(self, collation_hash):
        self.collation_validity[collation_hash] = False


    def init_shard(self, shard_id):
        self.collation_matrix[shard_id] = [[None]]
        self.collation_coordinate[GENESIS_HASH] = (0, 0)


    def get_shard_head_hash(self, shard_id):
        return get_collation_hash(self.shard_head[shard_id])


    def get_collation_hash_by_coordinate(self, shard_id, parent_kth, parent_height):
        collation = self.collation_matrix[shard_id][parent_height][parent_kth]
        return get_collation_hash(collation)


    def get_collation_coordinate_by_hash(self, collation_hash):
        return self.collation_coordinate[collation_hash]


    def is_collation_valid(self, collation_hash):
        return self.collation_validity[collation_hash]


class ShardingVisualization(object):

    NUM_TX_IN_BLOCK = 3
    EMPTY_TX = '&nbsp;' * 4
    GENESIS_HASH = b'\x00' * 32

    def __init__(self, filename, tester_chain, draw_in_period=False, show_events=True):
        self.record = tester_chain.record
        self.mainchain = tester_chain.chain
        self.draw_in_period = draw_in_period
        self.show_events = show_events
        self.min_hash = None
        self.mainchain_caption = "mainchain" if not draw_in_period else "period"

        self.layers = {}
        self.g = gv.Digraph('G', filename=filename)


    def draw_event_edge(self, node, prev_node):
        self.g.edge(node, prev_node, style='dashed', constraint='false')


    def draw_block(self, current_hash, prev_hash, label_edges, height):
        prev_node_name = self.get_node_name_from_hash(prev_hash)
        node_name = self.get_node_name_from_hash(current_hash)
        if self.draw_in_period:
            caption = '{}'.format(height)
        else:
            caption = 'B{}: {}'.format(height, node_name)
        self.draw_struct(node_name, prev_node_name, height, label_edges, 'record', caption)


    def draw_collation(self, current_hash, prev_hash, label_edges, height, order, is_valid=True):
        prev_node_name = self.get_node_name_from_hash(prev_hash)
        node_name = self.get_node_name_from_hash(current_hash)
        caption = 'C' if is_valid else 'IC'
        caption += '({}, {}): {}'.format(height, order, node_name)
        self.draw_struct(node_name, prev_node_name, height, label_edges, 'Mrecord', caption)
        if not is_valid:
            self.g.node(node_name, color='red', style='filled')


    def get_node_name_from_hash(self, node_hash):
        if self.draw_in_period and \
                node_hash in self.record.blocks:
            block_number = self.record.blocks[node_hash].number
            return str(block_number // self.mainchain.env.config['PERIOD_LENGTH'])
        if isinstance(node_hash, bytes):
            node_hash = get_shorten_hash(node_hash)
        return node_hash


    def get_labels_from_node(self, node_hash):
        '''returns a list of edge pairs from events in the node `node_hash` to other events
            e.g. [((current_hash, label), (prev_hash, prev_label)), ...]
        '''
        label_obj_list = self.record.get_tx_labels_from_node(node_hash)
        node_name = self.get_node_name_from_hash(node_hash)
        labels = []
        for label_obj in label_obj_list:
            # 'lable': label, 'prev_label': prev_label,
            # 'prev_label_node_hash': prev_label_node_hash,
            label = label_obj['label']
            prev_label = label_obj['prev_label']
            prev_label_node_name = self.get_node_name_from_hash(label_obj['prev_label_node_hash'])
            current_label_index = (node_name, label)
            if prev_label is None:
                prev_label_index = None
            else:
                prev_label_index = (prev_label_node_name, prev_label)
            edge = (current_label_index, prev_label_index)
            labels.append(edge)
        return labels


    def draw_struct(self, node_name, prev_node_name, height, label_edges, shape, caption):
        assert isinstance(height, int)
        label_list = [item[0][1] for item in label_edges]
        padding_num = ((len(label_list) // self.NUM_TX_IN_BLOCK) + 1) * self.NUM_TX_IN_BLOCK
        tx_labels_str = ''
        for i in range(padding_num):
            if i % self.NUM_TX_IN_BLOCK == 0:
                if i != 0:
                    tx_labels_str += ' | '
                tx_labels_str += '{'
            if i >= len(label_list):
                tx_labels_str += '<tx{}> '.format(i)
                tx_labels_str += self.EMPTY_TX
            else:
                tx_labels_str += '<{}> '.format(label_list[i])
                tx_labels_str += label_list[i]
            if (i % self.NUM_TX_IN_BLOCK) == (self.NUM_TX_IN_BLOCK - 1):
                tx_labels_str += '}'
            else:
                tx_labels_str += ' | '
        if len(label_list) > self.NUM_TX_IN_BLOCK:
            tx_labels_str = '{{' + tx_labels_str + '}}'
        if not self.show_events or len(label_list) == 0:
            struct_label = '{ %s }' % caption
        else:
            struct_label = '{ %s | %s }' % (caption, tx_labels_str)

        self.g.node(node_name, struct_label, shape=shape)
        self.g.edge(node_name, prev_node_name) # , weight=weight)

        # draw event edges
        if self.show_events:
            for edge in label_edges:
                label_index, prev_label_index = edge
                label_index_str = '{}:{}'.format(label_index[0], label_index[1])
                if prev_label_index is None:
                    continue
                prev_label_index_str = '{}:{}'.format(prev_label_index[0], prev_label_index[1])
                self.draw_event_edge(label_index_str, prev_label_index_str)


    def draw_mainchain(self, chain):
        # TODO: refactor!!

        # add longest chain to the record ####
        current_block = chain.head
        while current_block is not None:
            self.record.add_block(current_block)
            current_period = current_block.header.number // chain.env.config['PERIOD_LENGTH']
            if not self.draw_in_period:
                self.layers[self.get_node_name_from_hash(current_block.header.hash)] = []
            else:
                self.layers[str(current_period)] = []
            current_block = chain.get_parent(current_block)

        # record the highest node name
        self.min_hash = self.get_node_name_from_hash(chain.head.header.hash)

        self.g.node(self.mainchain_caption, shape='none')
        self.layers[self.mainchain_caption] = []

        tx_labels_in_current_period = []
        current_block_header = self.record.mainchain_head_header
        while current_block_header is not None:
            if current_block_header == self.record.mainchain_genesis_header:
                prev_block_header = None
                prev_block_hash = self.mainchain_caption
            else:
                prev_block_header = self.record.blocks[current_block_header.prevhash]
                prev_block_hash = prev_block_header.hash

            current_period = current_block_header.number // chain.env.config['PERIOD_LENGTH']

            label_edges = self.get_labels_from_node(current_block_header.hash)

            tx_labels_in_current_period = label_edges + tx_labels_in_current_period
            if not self.draw_in_period:
                self.draw_block(
                    current_block_header.hash,
                    prev_block_hash,
                    label_edges,
                    current_block_header.number,
                )
                self.layers[self.get_node_name_from_hash(current_block_header.hash)] = []
            elif current_block_header.number % chain.env.config['PERIOD_LENGTH'] == 0:
                self.draw_block(
                    current_block_header.hash,
                    prev_block_hash,
                    tx_labels_in_current_period,
                    current_period,
                )
                tx_labels_in_current_period = []
                self.layers[str(current_period)] = []
            current_block_header = prev_block_header


    def draw_shardchains(self, record):
        '''Assume that all collations are `add_collation`ed into the `self.record` before this
            method is called.
        '''
        for shard_id, collations in record.collations.items():
            shardchain_caption = "shard_" + str(shard_id)
            self.g.node(shardchain_caption, shape='none')
            self.layers[self.mainchain_caption].append(shardchain_caption)
            collations = record.collations[shard_id]
            for collation_hash, collation in collations.items():
                if collation_hash == self.GENESIS_HASH:
                    continue
                height, order = self.record.get_collation_coordinate_by_hash(collation_hash)
                name = self.get_node_name_from_hash(collation_hash)
                prev_hash = collation.header.parent_collation_hash
                if prev_hash == self.GENESIS_HASH:
                    prev_hash = shardchain_caption
                period_start_prevhash = self.get_node_name_from_hash(
                    collation.header.period_start_prevhash,
                )
                if self.draw_in_period:
                    self.layers[str(collation.header.expected_period_number)].append(name)
                else:
                    self.layers[period_start_prevhash].append(name)
                label_edges = self.get_labels_from_node(collation_hash)
                is_valid = self.record.is_collation_valid(collation_hash)
                self.draw_collation(collation_hash, prev_hash, label_edges, height, order, is_valid)


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
        self.set_rank(self.layers)

        print(self.g.source)
        self.g.view()
