from collections import defaultdict
import re
import rlp

from ethereum import utils
from ethereum.slogging import get_logger
from ethereum.transactions import Transaction
from ethereum.transaction_queue import TransactionQueue

from sharding import contract_utils, used_receipt_store_utils, validator_manager_utils
from sharding.collation import Collation, CollationHeader
from sharding.tools import tester

log_tl = get_logger('sharding.tl')

GENESIS_HASH = b'\x00' * 32
LABEL_BLOCK = 'B'
LABEL_COLLATION = 'C'
LABEL_DEPOSIT = 'D'
LABEL_RECEIPT = 'R'
LABEL_RECEIPT_CONSUMING = 'RC'
LABEL_TRANSACTION = 'T'
LABEL_WITHDRAW = 'W'
LABEL_ADD_HEADER = 'AH'
LEN_HASH = 8

def get_shorten_hash(hash_bytes32):
    # TODO: work around
    return hash_bytes32.hex()[:LEN_HASH]


def get_collation_hash(collation):
    if collation is None:
        return GENESIS_HASH
    return collation.header.hash


class Parser(object):
    def parse(self, test_string):
        cmds = []
        comment_pat = re.compile(r"#.*$")
        cmd_params_pat = re.compile(r"([A-Za-z]+)([0-9,]+)")
        for token in test_string.split('\n'):
            token = token.replace(' ', '')
            token = comment_pat.sub('', token)
            if token == '':
                continue
            cmd, params = cmd_params_pat.match(token).groups()
            if (cmd + params) != token:
                raise ValueError("Bad token")
            cmds.append((cmd, params))
        return cmds


class Record(object):

    def __init__(self):
        self.collations = defaultdict(dict)
        # self.collation_hash_index_map = {}
        # 'tx_hash' -> {'confirmed': 'node_hash', 'label': {'R'|'RC'|'D'|'W'|'TX', 'tx': tx}
        self.made_txs = {}
        # [{'shard_id', 'startgas', 'gasprice', 'to', 'value', 'data'}, ...]
        self.receipts = []
        # 'hash' -> ['tx_hash1', 'tx_hash2', ...]
        self.txs = {}
        # 'label' -> 'node_name'
        self.tx_label_node_map = {}
        # 'hash:label' -> previous 'hash:label'
        self.node_label_map = {}

        self.block_events = defaultdict(list)

        self.blocks = {}
        self.mainchain_head = None

        self.collation_map = {}
        # collation_hash -> (height, order)
        self.collation_coordinate = {}
        self.shard_head = {}


    def add_block(self, block):
        self.blocks[block.header.hash] = block
        if self.mainchain_head is None or self.mainchain_head.header.number < block.header.number:
            self.mainchain_head = block
        self.add_node_txs(block)


    def add_collation_old(self, collation):
        collation_hash = get_collation_hash(collation)
        self.collations[collation.header.shard_id][collation_hash] = collation
        self.add_node_txs(collation)


    def _add_made_tx(self, tx, label, number, shard_id=None):
        """shard_id=None indicates it's in mainchain
        """
        self.made_txs[tx.hash] = {
            'tx': tx,
            'confirmed': False,
            'label': label + str(number),
            'shard_id': shard_id,
        }


    def add_add_header(self, tx, number):
        self._add_made_tx(tx, LABEL_ADD_HEADER, number)


    def add_deposit(self, tx, validator_index):
        self._add_made_tx(tx, LABEL_DEPOSIT, validator_index)


    def add_withdraw(self, tx, validator_index):
        self._add_made_tx(tx, LABEL_WITHDRAW, validator_index)


    def add_receipt(self, tx, receipt_id, shard_id, startgas, gasprice, to, value, data):
        self._add_made_tx(tx, LABEL_RECEIPT, receipt_id)
        self.receipts.append({
            'shard_id': shard_id,
            'startgas': startgas,
            'gasprice': gasprice,
            'to': to,
            'value': value,
            'data': data,
            'consumed': False,
        })


    def get_receipt(self, receipt_id):
        return self.receipts[receipt_id]


    def add_receipt_consuming(self, tx, receipt_id, shard_id):
        self._add_made_tx(tx, LABEL_RECEIPT_CONSUMING, receipt_id, shard_id)
        self.receipts[receipt_id]['consumed'] = True


    def mark_tx_confirmed(self, tx_hash):
        self.made_txs[tx_hash]['confirmed'] = True


    def add_node_txs(self, node):
        """node can be either a block or a collation
        """
        node_hash = node.header.hash
        self.txs[node_hash] = []
        for tx in node.transactions:
            self.txs[node_hash].append(tx.hash)
            # TODO: it seems all txs events should be processed here
            if tx.hash in self.made_txs.keys():
                tx_info = self.made_txs[tx.hash]
                tx_label = tx_info['label']
                self.tx_label_node_map[tx_label] = node.header.hash
                print("!@# label, tx_label: {}, node_hash: {}".format(tx_label, node.header.hash))
                prev_label = self.get_prev_label(tx_label)
                if prev_label is not None:
                    prev_label_node_hash = self.tx_label_node_map[prev_label]
                    # print(
                    #     "!@# label, prev_label: {}, prev_node_hash: {}".format(
                    #         prev_label,
                    #         prev_label_node_hash,
                    #     )
                    # )
                    index = get_shorten_hash(node.header.hash) + ':' + tx_label
                    value = get_shorten_hash(prev_label_node_hash) + ':' + prev_label
                    self.node_label_map[index] = value


    # should be removed and add a block_tx_labels map
    def get_tx_labels_from_node(self, node_hash):
        labels = []
        if node_hash not in self.txs.keys():
            return labels
        for tx_hash in self.txs[node_hash]:
            if tx_hash in self.made_txs.keys():
                tx_info = self.made_txs[tx_hash]
                labels.append(tx_info['label'])
        return labels


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
            # receipt_id = int(param)
            # param = str(self.receipts[receipt_id]['shard_id'])
        else:
            return None
        return prev_cmd + param


    def add_collation(self, collation):
        parent_collation_hash = collation.header.parent_collation_hash
        parent_height, parent_kth = self.collation_coordinate[parent_collation_hash]
        shard_id = collation.header.shard_id
        shard_collation_map = self.collation_map[shard_id]
        insert_index = 0
        try:
            layer_at_height = shard_collation_map[parent_height + 1]

            assert len(shard_collation_map[parent_height]) > 0
            parent_ptr = len(shard_collation_map[parent_height]) - 1
            assert len(layer_at_height) > 0
            child_ptr = len(layer_at_height) - 1
            # iterate each child and find its parent
            # the first child whose parent's index is less than or equaled to the
            # target parent's index, we insert the new collation after the child.
            while child_ptr >= 0:
                while (parent_ptr >= 0) and \
                        (layer_at_height[child_ptr].header.parent_collation_hash != \
                        get_collation_hash(shard_collation_map[parent_height][parent_ptr])):
                    parent_ptr -= 1
                assert parent_ptr >= 0  # a child must have a parent
                if parent_ptr <= parent_kth:
                    insert_index = child_ptr
                    break
                child_ptr -= 1
        except IndexError:
            layer_at_height = []
            shard_collation_map.append(layer_at_height)


        layer_at_height.insert(insert_index, collation)

        # if it is the longest chain, set it as the shard head
        if len(layer_at_height) == 1:
            self.shard_head[shard_id] = collation

        self.add_collation_old(collation)

        self.add_node_txs(collation)

        self.collation_coordinate[collation.header.hash] = (parent_height + 1, insert_index)


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


class TestingLang(object):

    TX_VALUE = utils.denoms.gwei

    def __init__(self, parser=Parser(), record=Record()):
        self.parser = parser
        self.record = record

        self.c = tester.Chain(env='sharding', deploy_sharding_contracts=True)
        self.valmgr = tester.ABIContract(
            self.c,
            validator_manager_utils.get_valmgr_ct(),
            validator_manager_utils.get_valmgr_addr(),
        )

        self.current_validators = {}

        self.handlers = {}
        self.handlers[LABEL_BLOCK] = self.mine_block
        self.handlers[LABEL_COLLATION] = self.collate
        self.handlers[LABEL_DEPOSIT] = self.deposit_validator
        self.handlers[LABEL_RECEIPT] = self.mk_receipt
        self.handlers[LABEL_RECEIPT_CONSUMING] = self.mk_receipt_consuming_transaction
        self.handlers[LABEL_TRANSACTION] = self.mk_transaction
        self.handlers[LABEL_WITHDRAW] = self.withdraw_validator


    def execute(self, test_string=""):
        cmds = self.parser.parse(test_string)
        executed_cmds = ""
        for cmd, param_str in cmds:
            try:
                handler = self.handlers[cmd]
            except KeyError:
                print("Error at: " + executed_cmds + '"{}"'.format(cmd + param_str))
                raise ValueError('command "{}" not found'.format(cmd))
            try:
                handler(param_str)
            except:
                print("Error at: " + executed_cmds + '"{}"'.format(cmd + param_str))
                raise
            executed_cmds += (cmd + param_str + " ")


    def get_tester_chain(self):
        return self.c


    def update_collations(self):
        for value in self.c.chain.shard_id_list:
            self.c.update_collation(value)


    def _mine_and_update_head_collation(self, num_of_blocks):
        for i in range(num_of_blocks):
            block = self.c.mine(1)
            self.record.add_block(block)
        self.update_collations()


    def mine_block(self, param_str):
        try:
            num_of_blocks = int(param_str)
        except ValueError:
            num_of_blocks = 1
        self._mine_and_update_head_collation(num_of_blocks)


    def collate(self, param_str):
        """1) Ci    : create a collation based on the head collation in shard `i`
           2) Cs,i,j: create a collation based on the `j`th collation in the `i`th layer of the
                      shard chain tree in shard `s`
        """
        params_list = param_str.split(',')
        len_params_list = len(params_list)
        if len_params_list == 1:
            shard_id = int(params_list[0])
        elif len_params_list == 3:
            shard_id, parent_height, parent_kth = map(int, params_list)
        else:
            raise ValueError("Invalid number of parameters")

        if shard_id < 0:
            raise ValueError("Invalid shard_id")

        collator_valcode_addr = utils.parse_as_bin(self.valmgr.sample(shard_id))
        if collator_valcode_addr == (b'\x00' * 20):
            print("No collator in this period in shard {}".format(shard_id))
            return
        validator_index = self.current_validators[collator_valcode_addr]
        collator_privkey = tester.keys[validator_index]

        expected_period_number = self.c.chain.get_expected_period_number()

        if not self.c.chain.has_shard(shard_id):
            self.c.add_test_shard(shard_id)
            self.record.init_shard(shard_id)

        if len_params_list == 1:
            collation = self.c.collate(shard_id, collator_privkey)
            parent_collation_hash = collation.header.parent_collation_hash
            parent_height, parent_kth = self.record.get_collation_coordinate_by_hash(
                parent_collation_hash,
            )
        elif len_params_list == 3:
            if (parent_height < 0) or (parent_kth < 0):
                raise ValueError("Invalid shard_id")
            parent_collation_hash = self.record.get_collation_hash_by_coordinate(
                shard_id,
                parent_kth,
                parent_height,
            )
            txqueue = TransactionQueue()
            for tx in self.c.collation[shard_id].transactions:
                txqueue.add_transaction(tx)
            collation = self.c.generate_collation(
                shard_id=shard_id,
                coinbase=utils.privtoaddr(collator_privkey),
                key=collator_privkey,
                txqueue=txqueue,
                parent_collation_hash=parent_collation_hash,
            )
            period_start_prevblock = self.c.chain.get_block(collation.header.period_start_prevhash)
            self.c.chain.shards[shard_id].add_collation(
                collation,
                period_start_prevblock,
            )
            tx = validator_manager_utils.call_tx_add_header(
                self.c.head_state,
                collator_privkey,
                0,
                rlp.encode(collation.header),
            )
            self.c.direct_tx(tx)
        self.record.add_collation(collation)

        tx = self.c.block.transactions[-1]
        current_height = parent_height + 1
        self.record.add_add_header(tx, current_height)

        self.c.set_collation(
            shard_id,
            expected_period_number=expected_period_number,
            parent_collation_hash=self.record.get_shard_head_hash(shard_id),
        )


    def mk_receipt(self, param_str):
        """R0: make a receipt in shard 0
           default sender and receiver are the same, a0
        """
        params_list = param_str.split(',')
        shard_id = int(params_list[0])
        sender_index = recipient_index = 0
        sender_privkey = tester.keys[sender_index]
        to = tester.accounts[recipient_index]
        startgas = 200000
        gasprice = tester.GASPRICE
        value = self.TX_VALUE
        data = b''
        receipt_id = self.valmgr.tx_to_shard(
            to,
            shard_id,
            startgas,
            gasprice,
            data,
            sender=sender_privkey,
            value=value,
        )
        tx = self.c.block.transactions[-1]
        self.record.add_receipt(tx, receipt_id, shard_id, startgas, gasprice, to, value, data)


    def mk_receipt_consuming_transaction(self, param_str):
        """RC0: make a receipt-consuming tx which consumes the receipt 0
        """
        print("!@# mk_rctx: ", param_str)
        params_list = param_str.split(',')
        receipt_id = int(params_list[0])
        sender_index = recipient_index = 0
        sender_privkey = tester.keys[sender_index]
        receipt = self.record.get_receipt(receipt_id)
        tx = Transaction(
            0,
            receipt['gasprice'],
            receipt['startgas'],
            receipt['to'],
            receipt['value'],
            receipt['data'],
        )
        tx.v, tx.r, tx.s = 1, receipt_id, 0
        self.c.direct_tx(tx, shard_id=receipt['shard_id'])
        self.record.add_receipt_consuming(tx, receipt_id, receipt['shard_id'])


    def mk_transaction(self, param_str):
        """1) T,0,1: send ether from v0 to v1 in mainchain
           2) T0,1,2: send ether from v1 to v2 in shard 0
           3) T,0,1,2: send ether from v1 in mainchain to v2 in shard 0
        """
        params_list = param_str.split(',')
        if len(params_list) == 3:
            sender_index, recipient_index = int(params_list[1]), int(params_list[2])
            sender_privkey = tester.keys[sender_index]
            recipient_addr = tester.accounts[recipient_index]
            if params_list[0] == '':
                self.c.tx(sender=sender_privkey, to=recipient_addr, value=self.TX_VALUE)
            else:
                shard_id = int(params_list[0])
                self.c.tx(
                    sender=sender_privkey,
                    to=recipient_addr,
                    value=self.TX_VALUE,
                    shard_id=shard_id,
                )
        # make a receipt and consume it right away
        elif len(params_list) == 4 and params_list[0] == '':
            shard_id = int(params_list[1])
            sender_index, recipient_index = int(params_list[2]), int(params_list[3])
            sender_privkey = tester.keys[sender_index]
            recipient_addr = tester.accounts[recipient_index]
            startgas = 200000
            data = b''
            receipt_id = self.valmgr.tx_to_shard(
                recipient_addr,
                shard_id,
                startgas,
                tester.GASPRICE,
                data,
                sender=sender_privkey,
                value=self.TX_VALUE,
            )
            tx = Transaction(0, tester.GASPRICE, startgas, recipient_addr, self.TX_VALUE, data)
            tx.v, tx.r, tx.s = 1, receipt_id, 0
            self.c.direct_tx(tx, shard_id=shard_id)
        else:
            raise ValueError("Invalid parameters")


    def deposit_validator(self, param_str):
        validator_index = int(param_str)
        privkey = tester.keys[validator_index]
        valcode_addr = self.c.sharding_valcode_addr(privkey)
        ret_addr = utils.privtoaddr(utils.sha3("ret_addr"))
        self.c.sharding_deposit(privkey, valcode_addr)
        self.current_validators[valcode_addr] = validator_index
        tx = self.c.block.transactions[-1]
        self.record.add_deposit(tx, validator_index)


    def withdraw_validator(self, param_str):
        validator_index = int(param_str)
        # result == False when `withdraw` fails
        # result = self.c.sharding_withdraw(tester.keys[validator_index], validator_index)
        result = self.valmgr.withdraw(
            validator_index,
            contract_utils.sign(
                validator_manager_utils.WITHDRAW_HASH,
                tester.keys[validator_index]
            )
        )
        if not result:
            raise ValueError("Withdraw failed")
        tx = self.c.block.transactions[-1]
        self.record.add_withdraw(tx, validator_index)
