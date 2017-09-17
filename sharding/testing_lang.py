import re

from ethereum import utils
from ethereum.slogging import get_logger

from sharding import used_receipt_store_utils, validator_manager_utils
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
        self.valmgr = self.c.contract(validator_manager_utils.get_valmgr_code(), language='viper')
        self.c.mine(5)
        self.current_validators = {}
        self.handlers = {}
        self.handlers['B'] = self.handle_B
        self.handlers['C'] = self.handle_C
        self.handlers['D'] = self.handle_D
        self.handlers['W'] = self.handle_W


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


    def handle_B(self, param_str):
        try:
            number = int(param_str)
        except ValueError:
            number = 1
        self.c.mine(number)


    def handle_C(self, param_str):
        shard_id, number = map(int, param_str.split(','))
        collator_valcode_addr = utils.parse_as_bin(self.valmgr.sample(shard_id))
        if collator_valcode_addr == (b'\x00' * 20):
            print("No collator in this period in shard {}".format(shard_id))
            return
        validator_index = self.current_validators[collator_valcode_addr]
        collator_privkey = tester.keys[validator_index]
        if not self.c.chain.has_shard(shard_id):
            self.c.add_test_shard(shard_id)
        collation = self.c.collate(shard_id, collator_privkey)
        expected_period_number = self.c.chain.get_expected_period_number()
        self.c.set_collation(
            shard_id,
            expected_period_number=expected_period_number,
            parent_collation_hash=collation.header.hash
        )


    def handle_D(self, param_str):
        validator_index = int(param_str)
        privkey = tester.keys[validator_index]
        valcode_addr = self.c.sharding_valcode_addr(privkey)
        ret_addr = utils.privtoaddr(utils.sha3("ret_addr"))
        # self.c.sharding_deposit(privkey, valcode_addr)
        self.valmgr.deposit(valcode_addr, ret_addr, value=100*utils.denoms.ether)
        self.current_validators[valcode_addr] = validator_index


    def handle_W(self, param_str):
        validator_index = int(param_str)
        # result == False when `withdraw` fails
        result = self.valmgr.withdraw(
            validator_index,
            validator_manager_utils.sign(
                validator_manager_utils.WITHDRAW_HASH,
                tester.keys[validator_index]
            )
        )


def test_testing_lang():
    tl = TestingLang(Parser())
    tl.execute("B2 D0 W0 D0 C0,2 B5 C0,2")
