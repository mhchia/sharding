import re

from ethereum import utils
from ethereum.slogging import get_logger

from sharding import used_receipt_store_utils, validator_manager_utils
from sharding.collation import Collation
from sharding.tools import tester

log_tl = get_logger('sharding.tl')

class Parser(object):
    def parse(self, test_string):
        cmds = []
        for token in test_string.split(' '):
            cmd, params = re.match("([A-Za-z]+)([0-9,]+)", token).groups()
            if (cmd + params) != token:
                raise ValueError("Bad token")
            cmds.append((cmd, params))
        return cmds


class TestingLang(object):
    def __init__(self, parser):
        self.parser = parser
        self.c = tester.Chain(env='sharding', deploy_sharding_contracts=True)
        self.valmgr = tester.ABIContract(
            self.c,
            validator_manager_utils.get_valmgr_ct(),
            validator_manager_utils.get_valmgr_addr()
        )
        self.c.mine(5)
        # self.update_collations()
        self.latest_collation = {}
        self.current_validators = {}
        self.handlers = {}
        self.handlers['B'] = self.mine_block
        self.handlers['C'] = self.collate
        self.handlers['D'] = self.deposit_validator
        self.handlers['W'] = self.withdraw_validator


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


    def test_zero_hash(self):
        print(self.valmgr.test_zero_hash(b'\x00' * 32))


    def update_collations(self):
        for value in self.c.chain.shard_id_list:
            self.c.update_collation(value)


    def _mine_and_update_head_collation(self, num_of_blocks):
        self.c.mine(num_of_blocks)
        self.update_collations()


    def mine_block(self, param_str):
        try:
            num_of_blocks = int(param_str)
        except ValueError:
            num_of_blocks = 1
        self._mine_and_update_head_collation(num_of_blocks)


    def collate(self, param_str):
        shard_id, number = map(int, param_str.split(','))
        collator_valcode_addr = utils.parse_as_bin(self.valmgr.sample(shard_id))
        print("!@# collator_valcode_addr: ", collator_valcode_addr)
        if collator_valcode_addr == (b'\x00' * 20):
            print("No collator in this period in shard {}".format(shard_id))
            return
        validator_index = self.current_validators[collator_valcode_addr]
        collator_privkey = tester.keys[validator_index]
        if not self.c.chain.has_shard(shard_id):
            self.c.add_test_shard(shard_id)
            self.latest_collation[shard_id] = None
            # print("!@# head_hash: ", self.c.chain.shards[shard_id].head_hash)
            # print("!@#score123: ", self.valmgr.get_colhdr(shard_id, collation.header.hash))
            # print("!@#score1233: ", self.c.chain.shards[shard_id].get_score(collation.header))
            # self.c.update_collation(shard_id)
        else:
            pass
            # self.c.update_collation(shard_id, parent_collation_hash=self.latest_collation[shard_id])
            # print("!@#head_hash: ", self.c.chain.shards[shard_id].head_hash)
            # print("!@#score1234: ", self.valmgr.get_collation_headers__score(shard_id, collation.header.hash))
            # print("!@#score12344: ", self.c.chain.shards[shard_id].get_score(collation.header))
            # print("!@# head_hash: ", self.c.chain.shards[shard_id].head_hash)
        expected_period_number = self.c.chain.get_expected_period_number()
        collation = Collation(self.c.collate(shard_id, collator_privkey))
        self.c.set_collation(
            shard_id,
            expected_period_number=expected_period_number,
            parent_collation_hash=collation.header.hash,
        )
        print("!@#score123: ", self.valmgr.get_colhdr(shard_id, collation.header.hash))
        self.latest_collation[shard_id] = collation.header.hash
        # print("collation_header_parent", self.valmgr.get_collation_headers__parent_collation_hash(shard_id, collation.header.hash))
        # print("collation_header_score", self.valmgr.get_collation_headers__score(shard_id, collation.header.hash))


    def deposit_validator(self, param_str):
        validator_index = int(param_str)
        privkey = tester.keys[validator_index]
        valcode_addr = self.c.sharding_valcode_addr(privkey)
        ret_addr = utils.privtoaddr(utils.sha3("ret_addr"))
        self.c.sharding_deposit(privkey, valcode_addr)
        # print("!@# deposit: ", self.valmgr.deposit(valcode_addr, ret_addr, value=100*utils.denoms.ether))
        self.current_validators[valcode_addr] = validator_index


    def withdraw_validator(self, param_str):
        validator_index = int(param_str)
        # result == False when `withdraw` fails
        # result = self.c.sharding_withdraw(tester.keys[validator_index], validator_index)
        result = self.valmgr.withdraw(
            validator_index,
            validator_manager_utils.sign(
                validator_manager_utils.WITHDRAW_HASH,
                tester.keys[validator_index]
            )
        )


def test_testing_lang():
    tl = TestingLang(Parser())
    tl.execute("D0 B5 C0,2 C0,2 C0,2 B5 C0,2 C0,2 B5")
    # tl.test_zero_hash()
