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
    def __init__(self, parser):
        self.parser = parser
        self.c = tester.Chain(env='sharding', deploy_sharding_contracts=True)
        self.valmgr = tester.ABIContract(
            self.c,
            validator_manager_utils.get_valmgr_ct(),
            validator_manager_utils.get_valmgr_addr(),
        )
        self.c.mine(5)
        # self.update_collations()
        self.latest_collation = {}
        self.collation_map = {}
        self.shard_head = {}
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

        collator_valcode_addr = utils.parse_as_bin(self.valmgr.sample(shard_id))
        if collator_valcode_addr == (b'\x00' * 20):
            print("No collator in this period in shard {}".format(shard_id))
            return
        validator_index = self.current_validators[collator_valcode_addr]
        collator_privkey = tester.keys[validator_index]
        if not self.c.chain.has_shard(shard_id):
            self.c.add_test_shard(shard_id)
            self.collation_map[shard_id] = []
            self.collation_map[shard_id].append(
                [{'hash': b'\x00' * 32, 'parent_hash': None, 'parent_kth': -1}],
            )
            self.latest_collation[shard_id] = None

        if len_params_list == 3:
            shard_collation_map = self.collation_map[shard_id]
            parent_collation_hash = shard_collation_map[parent_height][parent_kth]['hash']
            collation = self.c.generate_collation(
                shard_id=shard_id,
                coinbase=utils.privtoaddr(collator_privkey),
                key=collator_privkey,
                txqueue=None,
                parent_collation_hash=parent_collation_hash,
            )
            period_start_prevblock = self.c.chain.get_block(collation.header.period_start_prevhash)
            self.c.chain.shards[shard_id].add_collation(
                collation,
                period_start_prevblock,
                self.c.chain.handle_ignored_collation,
            )
            try:
                layer_at_height = shard_collation_map[parent_height + 1]
            except IndexError:
                layer_at_height = []
                shard_collation_map.append(layer_at_height)
            # TODO: not sure if using binary search will help?
            #       in average case the num of collations at a certain height
            #       should be small
            ind = 0
            while ind < len(layer_at_height):
                if layer_at_height[ind]['parent_kth'] < parent_kth:
                    break
                ind += 1
            # TODO: the field `parent_kth` would be wrong when there is a new collation
            #       inserted before the parent in the list
            #       [Possible solution]: record all reference to the children collations of a
            #           collation, when a collation is inserted, iterate all affected collations
            #           and update their `parent_kth`. This takes O(k^2), which k is the node
            #           degree of a node
            collation_obj = {
                    'hash': collation.header.hash,
                    'height': parent_height + 1,
                    'parent_hash': parent_collation_hash,
                    'parent_kth': parent_kth,
            }
            layer_at_height.insert(ind, collation_obj)
            # if it is the longest chain, set it as the shard head
            if len(layer_at_height) == 1:
                self.shard_head[shard_id] = collation_obj
        else:
            # TODO: also record the created collations in the self.collation_map
            expected_period_number = self.c.chain.get_expected_period_number()
            collation = Collation(self.c.collate(shard_id, collator_privkey))
            self.c.set_collation(
                shard_id,
                expected_period_number=expected_period_number,
                parent_collation_hash=collation.header.hash,
            )
            self.latest_collation[shard_id] = collation.header.hash


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
            validator_manager_utils.sign(
                validator_manager_utils.WITHDRAW_HASH,
                tester.keys[validator_index]
            )
        )
        if not result:
            raise ValueError("Withdraw failed")


def test_testing_lang():
    tl = TestingLang(Parser())
    # tl.execute("D0 W0 D0 B5 C0 C0 C0 B5 C0 C0 B5 C0 C0 C0,0,0 C0,1,0 C1,0,0")
    cmds = """
    D0 # deposit validator 0
    W0 # withdraw validator 0
    D0
    B5
    C0
    C0
    C0
    B5
    C0
    C0
    B5
    C0
    C0
    C0,0,0
    C0,1,0
    C1,0,0
#    C2,1,0
"""
    tl.execute(cmds)
