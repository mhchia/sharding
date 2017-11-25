import time

from ethereum import utils
from ethereum.tools import tester as t
import rlp
from solc import compile_source
from viper import compiler
from web3 import Web3, HTTPProvider, TestRPCProvider
from web3.contract import ConciseContract

from sharding import contract_utils, validator_manager_utils
from sharding.config import sharding_config


# web3 = Web3(IPCProvider())
# web3 = Web3(TestRPCProvider())


class RPCHandler:

    PASSPHRASE = '123'
    DEPOSIT_VALUE = sharding_config['DEPOSIT_SIZE']

    def __init__(self, rpc_server_url='http://localhost:8545'):
        self._w3 = Web3(HTTPProvider(rpc_server_url))
        self.init_vmc_attributes()
        self.setup_vmc_instance()


    def init_vmc_attributes(self):
        self._vmc_addr = utils.checksum_encode(validator_manager_utils.get_valmgr_addr())
        self._vmc_sender_addr = utils.checksum_encode(
            validator_manager_utils.get_valmgr_sender_addr(),
        )
        self._vmc_bytecode = validator_manager_utils.get_valmgr_bytecode()
        self._vmc_code = validator_manager_utils.get_valmgr_code()
        self._vmc_abi = compiler.mk_full_signature(self._vmc_code)
        self._vmc_ct = validator_manager_utils.get_valmgr_ct()

        # addr -> validation_code_addr
        self.valcodes = {}


    # RPC related

    def get_block_number(self):
        return self._w3.eth.blockNumber


    def get_nonce(self, address):
        address = utils.checksum_encode(address)
        return self._w3.eth.getTransactionCount(address)


    def import_privkey(self, privkey):
        '''
            @privkey: bytes
        '''
        passphrase = self.PASSPHRASE
        self._w3.personal.importRawKey(privkey, passphrase)


    def is_vmc_deployed(self):
        return self._w3.eth.getCode(self._vmc_addr) != b''


    def deploy_contract(self, bytecode, address):
        self.unlock_account(t.a0)
        self._w3.eth.sendTransaction({"from": utils.checksum_encode(address), "data": bytecode})


    def direct_tx(self, tx):
        raw_tx = rlp.encode(tx)
        raw_tx_hex = self._w3.toHex(raw_tx)
        result = self._w3.eth.sendRawTransaction(raw_tx_hex)


    def deploy_vmc(self):
        print("!@# deploy_vmc")
        vmc_tx = validator_manager_utils.get_valmgr_tx()
        self.direct_tx(vmc_tx)


    def setup_vmc_instance(self):
        if not self.is_vmc_deployed():
            self.deploy_vmc()
        self._vmc = self._w3.eth.contract(
            self._vmc_addr,
            abi=self._vmc_abi,
            bytecode=self._vmc_bytecode,
        )


    def mine(self, number):
        '''
        '''
        expected_block_number = self.get_block_number() + number
        self._w3.miner.start(1)
        while self.get_block_number() < expected_block_number:
            time.sleep(0.1)
        self._w3.miner.stop()


    def unlock_account(self, account):
        account = utils.checksum_encode(account)
        passphrase = self.PASSPHRASE
        self._w3.personal.unlockAccount(account, passphrase)


    # vmc related #############################

    def sample(self, shard_id):
        '''sample(shard_id: num) -> address
        '''
        return self._vmc.call().sample(shard_id)


    def deposit(self, validation_code_addr, return_addr, privkey):
        '''deposit(validation_code_addr: address, return_addr: address) -> num
        '''
        address = utils.checksum_encode(utils.privtoaddr(privkey))
        validation_code_addr = utils.checksum_encode(validation_code_addr)
        return_addr = utils.checksum_encode(return_addr)
        self.unlock_account(address)
        gas = sharding_config['CONTRACT_CALL_GAS']['VALIDATOR_MANAGER']['deposit']
        result = self._vmc.transact({
            'from': address,
            'value': self.DEPOSIT_VALUE,
            'gas': 510000,
        }).deposit(validation_code_addr, return_addr)
        print("!@# deposit:", result)


    def withdraw(self,
            validator_index,
            sig,
            privkey,
            gas=sharding_config['CONTRACT_CALL_GAS']['VALIDATOR_MANAGER']['withdraw']):
        '''withdraw(validator_index: num, sig: bytes <= 1000) -> bool
        '''
        address = utils.checksum_encode(utils.privtoaddr(privkey))
        self.unlock_account(address)
        # result = self._vmc.transact({
        #     'from': address,
        #     'gas': gas,
        # }).withdraw(validator_index, sig)
        self._vmc.transact({'from': address, 'gas': 210000}).withdraw(
            validator_index,
            contract_utils.sign(validator_manager_utils.WITHDRAW_HASH, t.keys[validator_index]),
        )


    def get_shard_list(self):
        '''get_shard_list(valcode_addr: address) -> bool[100]
        '''
        pass


    def add_header(self, ):
        '''add_header(header: bytes <= 4096) -> bool
        '''
        pass


    # utils #######################################################

    def deploy_valcode_and_deposit(self, validator_index):
        privkey = t.keys[validator_index]
        address = utils.privtoaddr(privkey)
        # address = utils.checksum_encode(address)
        self.unlock_account(address)
        if address not in self.valcodes:
            valcode = validator_manager_utils.mk_validation_code(address)
            nonce = self.get_nonce(address)
            valcode_addr = utils.mk_contract_address(address, nonce)
            self.unlock_account(address)
            self.deploy_contract(valcode, address)
            self.valcodes[address] = valcode_addr
            self.deposit(valcode_addr, address, privkey)


def print_current_contract_address(sender_address, nonce):
    list_addresses = [
        utils.checksum_encode(utils.mk_contract_address(t.a0, i)) for i in range(nonce + 1)
    ]
    print(list_addresses)


def import_tester_keys(rpc_handler):
    for i in t.keys:
        try:
            rpc_handler.import_privkey(i)
        except ValueError:
            pass


def first_setup_and_deposit(rpc_handler, validator_index):
    rpc_handler.mine(1)
    rpc_handler.deploy_valcode_and_deposit(validator_index)
    # TODO: error occurs when we don't mine so many blocks
    rpc_handler.mine(sharding_config['SHUFFLING_CYCLE_LENGTH'])


def do_withdraw(rpc_handler, validator_index):
    assert validator_index <= len(t.keys)
    privkey = t.keys[validator_index]
    addr = utils.checksum_encode(utils.privtoaddr(privkey))
    signature = contract_utils.sign(validator_manager_utils.WITHDRAW_HASH, privkey)
    rpc_handler.withdraw(validator_index, signature, privkey)
    # rpc_handler._vmc.transact(
    #     {'from': addr, 'gas': 210000}
    # ).withdraw(0, contract_utils.sign(validator_manager_utils.WITHDRAW_HASH, t.keys[validator_index]))
    rpc_handler.mine(1)


def main():
    validator_index = 0
    primary_key = t.keys[validator_index]
    primary_addr = t.accounts[validator_index]
    zero_addr = utils.checksum_encode(utils.int_to_addr(0))

    rpc = RPCHandler()

    if rpc.get_block_number() == 0:
        import_tester_keys(rpc)
        first_setup_and_deposit(rpc, validator_index)

    # rpc.deploy_valcode_and_deposit(validator_index); rpc.mine(1)

    # sampled_valcode = rpc.sample(1)
    # print(rpc._vmc.call().withdraw(validator_index, contract_utils.sign(validator_manager_utils.WITHDRAW_HASH, t.keys[validator_index])))
    print("!@# sample(): ", rpc.sample(0))
    # print("!@# is_stack_empty()", rpc._vmc.call().is_stack_empty())
    # print("!@# stack_pop()", rpc._vmc.call().stack_pop())
    print("!@# get_num_validators(): ", rpc._vmc.call().get_num_validators())
    # if sampled_valcode != zero_addr:
    #     do_withdraw(rpc, validator_index)
    # rpc.mine(25)
    addr = utils.checksum_encode(primary_addr)
    rpc.unlock_account(addr)
    # rpc._vmc.transact(
    #     {'from': addr, 'gas': 210000}
    # ).withdraw(validator_index, contract_utils.sign(validator_manager_utils.WITHDRAW_HASH, t.keys[validator_index]))
    # rpc.mine(1)

    # do_withdraw(rpc, validator_index)
    print("!@# sample(): ", rpc.sample(0))
    # print("!@# is_stack_empty()", rpc._vmc.call().is_stack_empty())
    # print("!@# stack_pop()", rpc._vmc.call().stack_pop())
    print("!@# get_num_validators(): ", rpc._vmc.call().get_num_validators())

    # print(rpc.get_block_number())
    # rpc.mine(5)
    # print(rpc.get_block_number())

if __name__ == '__main__':
    main()
