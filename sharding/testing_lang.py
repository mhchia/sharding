import re
import rlp

from ethereum import utils
from ethereum.slogging import get_logger
from ethereum.transactions import Transaction
from ethereum.transaction_queue import TransactionQueue

from sharding import (
    contract_utils,
    used_receipt_store_utils,
    validator_manager_utils,
)
from sharding.collation import Collation, CollationHeader
from sharding.tools import tester
from sharding.visualization import *

log_tl = get_logger('sharding.tl')


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


class TestingLang(object):

    TX_VALUE = utils.denoms.gwei

    def __init__(self, parser=Parser()):
        self.parser = parser

        self.c = tester.Chain(env='sharding', deploy_sharding_contracts=True)
        self.valmgr = tester.ABIContract(
            self.c,
            validator_manager_utils.get_valmgr_ct(),
            validator_manager_utils.get_valmgr_addr(),
        )
        self.receipts = []

        self.current_validators = {}

        self.handlers = {}
        self.handlers[LABEL_BLOCK] = self.mine_block
        self.handlers[LABEL_INVALID_COLLATION] = self.add_invalid_collation
        self.handlers[LABEL_COLLATION] = self.add_valid_collation
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


    def get_current_collator_privkey(self, shard_id):
        collator_valcode_addr = utils.parse_as_bin(self.valmgr.sample(shard_id))
        if collator_valcode_addr == (b'\x00' * 20):
            print("No collator in this period in shard {}".format(shard_id))
            return
        validator_index = self.current_validators[collator_valcode_addr]
        collator_privkey = tester.keys[validator_index]
        return collator_privkey


    def update_collations(self):
        for value in self.c.chain.shard_id_list:
            self.c.update_collation(value)


    def _mine_and_update_head_collation(self, num_of_blocks):
        for i in range(num_of_blocks):
            block = self.c.mine(1)
            self.c.record.add_block(block)
        self.update_collations()


    def mine_block(self, param_str):
        try:
            num_of_blocks = int(param_str)
        except ValueError:
            num_of_blocks = 1
        self._mine_and_update_head_collation(num_of_blocks)


    def mk_raw_collation(self, shard_id, parent_collation_hash, txs, collator_privkey=None):
        tester_chain = self.get_tester_chain()
        if collator_privkey is None:
            collator_privkey = self.get_current_collator_privkey(shard_id)
        txqueue = TransactionQueue()
        for tx in txs:
            txqueue.add_transaction(tx)
        collation = tester_chain.generate_collation(
            shard_id=shard_id,
            coinbase=utils.privtoaddr(collator_privkey),
            key=collator_privkey,
            txqueue=txqueue,
            parent_collation_hash=parent_collation_hash,
        )
        return collation


    def add_invalid_collation(self, param_str):
        '''Create a collation whose header will be accepted by the vmc,
            however, its tx_list_root is invalid.
           1) ICs    : create an invalid collation based on the
           2) ICs,i,j: create an invalid collation based on the `j`th collation in the `i`th layer
                       of the shard chain tree in shard `s`
        '''
        params_list = param_str.split(',')
        len_params_list = len(params_list)
        if len_params_list == 1:
            shard_id = int(params_list[0])
        elif len_params_list == 3:
            shard_id, parent_height, parent_kth = map(int, params_list)
            if (parent_height < 0) or (parent_kth < 0):
                raise ValueError("Invalid height or order")
        else:
            raise ValueError("Invalid number of parameters")

        if shard_id < 0:
            raise ValueError("Invalid shard_id")

        if not self.c.chain.has_shard(shard_id):
            self.c.add_test_shard(shard_id)
            self.c.record.init_shard(shard_id)

        if len_params_list == 1:
            parent_collation_hash = self.c.chain.shards[shard_id].head_hash
            parent_height, parent_kth = self.c.record.get_collation_coordinate_by_hash(
                parent_collation_hash,
            )
        elif len_params_list == 3:
            if (parent_height < 0) or (parent_kth < 0):
                raise ValueError("Invalid shard_id")
            parent_collation_hash = self.c.record.get_collation_hash_by_coordinate(
                shard_id,
                parent_kth,
                parent_height,
            )
        collator_privkey = self.get_current_collator_privkey(shard_id)
        collation = self.mk_raw_collation(
            shard_id,
            parent_collation_hash,
            [],
            collator_privkey,
        )
        collation.header.tx_list_root = b'bad_root' * 4
        collation.header.sig = contract_utils.sign(collation.signing_hash, collator_privkey)

        tx = validator_manager_utils.call_tx_add_header(
            self.c.head_state,
            collator_privkey,
            0,
            rlp.encode(collation.header),
        )
        self.c.direct_tx(tx)
        self.c.record.add_collation(collation)
        # `add_collation` to trigger callback functions in `invalid_collation_listeners`
        period_start_prevblock = self.c.chain.get_block(collation.header.period_start_prevhash)
        self.c.chain.shards[shard_id].add_collation(
            collation,
            period_start_prevblock,
        )


    def add_valid_collation(self, param_str):
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
            if (parent_height < 0) or (parent_kth < 0):
                raise ValueError("Invalid height or order")
        else:
            raise ValueError("Invalid number of parameters")

        if shard_id < 0:
            raise ValueError("Invalid shard_id")

        collator_privkey = self.get_current_collator_privkey(shard_id)
        expected_period_number = self.c.chain.get_expected_period_number()

        if not self.c.chain.has_shard(shard_id):
            self.c.add_test_shard(shard_id)
            self.c.record.init_shard(shard_id)

        if len_params_list == 1:
            collation = self.c.collate(shard_id, collator_privkey)
            parent_collation_hash = collation.header.parent_collation_hash
            parent_height, parent_kth = self.c.record.get_collation_coordinate_by_hash(
                parent_collation_hash,
            )
        elif len_params_list == 3:
            if (parent_height < 0) or (parent_kth < 0):
                raise ValueError("Invalid shard_id")
            parent_collation_hash = self.c.record.get_collation_hash_by_coordinate(
                shard_id,
                parent_kth,
                parent_height,
            )
            collation = self.mk_raw_collation(
                shard_id,
                parent_collation_hash,
                self.c.collation[shard_id].transactions,
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
        self.c.record.add_collation(collation)

        # FIXME: why parent_collation_hash=self.c.chain.shards[shard_id].head.hash doesn't work?
        self.c.set_collation(
            shard_id,
            expected_period_number=expected_period_number,
            parent_collation_hash=self.c.record.get_shard_head_hash(shard_id),
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
        self.receipts.append({
            'shard_id': shard_id,
            'startgas': startgas,
            'gasprice': gasprice,
            'to': to,
            'value': value,
            'data': data,
            'consumed': False,
        })


    def mk_receipt_consuming_transaction(self, param_str):
        """RC0: make a receipt-consuming tx which consumes the receipt 0
        """
        params_list = param_str.split(',')
        receipt_id = int(params_list[0])
        receipt = self.receipts[receipt_id]
        tx = Transaction(
            0,
            receipt['gasprice'],
            receipt['startgas'],
            receipt['to'],
            receipt['value'],
            receipt['data'],
        )
        tx.v, tx.r, tx.s = 1, receipt_id, 0
        result = self.c.direct_tx(tx, shard_id=receipt['shard_id'])


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
