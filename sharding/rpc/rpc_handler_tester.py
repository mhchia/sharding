import time

from ethereum import utils
import rlp
from solc import compile_source
from viper import compiler
from web3 import Web3, HTTPProvider, TestRPCProvider
from web3.contract import ConciseContract

from sharding import contract_utils, validator_manager_utils
from sharding.config import sharding_config
from sharding.tools import tester as t

# web3 = Web3(IPCProvider())
# web3 = Web3(TestRPCProvider())


accounts = []
keys = []

for account_number in range(10):
    keys.append(utils.sha3(utils.to_string(account_number)))
    accounts.append(utils.privtoaddr(keys[-1]))

# TODO: fix it, only for faster testing
sharding_config['SHUFFLING_CYCLE_LENGTH'] = 5

class BaseChainHandler:

    # RPC related

    def get_block(self, block_number):
        raise NotImplementedError("Must be implemented by subclasses")

    def get_block_number(self):
        raise NotImplementedError("Must be implemented by subclasses")

    def get_nonce(self, address):
        raise NotImplementedError("Must be implemented by subclasses")

    def import_privkey(self, privkey):
        raise NotImplementedError("Must be implemented by subclasses")

    def is_vmc_deployed(self):
        raise NotImplementedError("Must be implemented by subclasses")

    def deploy_contract(self, bytecode, privkey):
        raise NotImplementedError("Must be implemented by subclasses")

    def direct_tx(self, tx):
        raise NotImplementedError("Must be implemented by subclasses")

    def deploy_initiating_contracts(self, privkey):
        print("!@# deploy_initiating_contracts")
        if not self.is_vmc_deployed():
            addr = utils.checksum_encode(utils.privtoaddr(privkey))
            nonce = self.get_nonce(addr)
            print("!@# nonce={}".format(nonce))
            txs = validator_manager_utils.mk_initiating_contracts(privkey, nonce)
            for tx in txs[:3]:
                self.direct_tx(tx)
            self.mine(1)
            for tx in txs[3:]:
                self.direct_tx(tx)
            self.mine(1)

    def setup_vmc_instance(self):
        raise NotImplementedError("Must be implemented by subclasses")

    def mine(self, number):
        raise NotImplementedError("Must be implemented by subclasses")

    def unlock_account(self, account):
        raise NotImplementedError("Must be implemented by subclasses")

    # vmc related #############################

    def sample(self, shard_id):
        '''sample(shard_id: num) -> address
        '''
        raise NotImplementedError("Must be implemented by subclasses")

    def deposit(self, validation_code_addr, return_addr, privkey):
        '''deposit(validation_code_addr: address, return_addr: address) -> num
        '''
        raise NotImplementedError("Must be implemented by subclasses")

    def withdraw(self,
            validator_index,
            sig,
            privkey,
            gas=sharding_config['CONTRACT_CALL_GAS']['VALIDATOR_MANAGER']['withdraw']):
        '''withdraw(validator_index: num, sig: bytes <= 1000) -> bool
        '''
        raise NotImplementedError("Must be implemented by subclasses")

    def add_header(self, header, privkey):
        '''add_header(header: bytes <= 4096) -> bool
        '''
        raise NotImplementedError("Must be implemented by subclasses")

    def get_period_start_prevhash(self, expected_period_number):
        '''get_period_start_prevhash(expected_period_number: num) -> bytes32
        '''
        raise NotImplementedError("Must be implemented by subclasses")

    def tx_to_shard(self, to, tx_startgas, tx_gasprice, data):
        '''tx_to_shard(
            to: address, shard_id: num, tx_startgas: num, tx_gasprice: num, data: bytes <= 4096
           ) -> num
        '''
        raise NotImplementedError("Must be implemented by subclasses")

    def get_collation_gas_limit(self):
        '''get_collation_gas_limit() -> num
        '''
        raise NotImplementedError("Must be implemented by subclasses")

    def get_collation_header_score(self, shard_id, collation_header_hash):
        raise NotImplementedError("Must be implemented by subclasses")

    def get_num_validators(self):
        raise NotImplementedError("Must be implemented by subclasses")

    # utils #######################################################

    def deploy_valcode_and_deposit(self, validator_index):
        privkey = keys[validator_index]
        address = utils.privtoaddr(privkey)
        # address = utils.checksum_encode(address)
        self.unlock_account(address)
        valcode = validator_manager_utils.mk_validation_code(address)
        nonce = self.get_nonce(address)
        valcode_addr = utils.mk_contract_address(address, nonce)
        print("!@# valcode_addr=", valcode_addr)
        self.unlock_account(address)
        self.deploy_contract(valcode, privkey)
        self.deposit(valcode_addr, address, privkey)


class TesterChainHandler(BaseChainHandler):

    def __init__(self):
        self.tester_chain = t.Chain(env='sharding', deploy_sharding_contracts=False)
        self.init_vmc_attributes()
        self.setup_vmc_instance()

    def init_vmc_attributes(self):
        self._vmc_addr = validator_manager_utils.get_valmgr_addr()
        print("!@# vmc_addr={}".format(self._vmc_addr))
        self._vmc_sender_addr = validator_manager_utils.get_valmgr_sender_addr()
        print("!@# vmc_sender_addr={}".format(self._vmc_sender_addr))
        self._vmc_bytecode = validator_manager_utils.get_valmgr_bytecode()
        self._vmc_code = validator_manager_utils.get_valmgr_code()
        self._vmc_abi = compiler.mk_full_signature(self._vmc_code)
        # print("!@# vmc_abi={}".format(self._vmc_abi))
        self._vmc_ct = validator_manager_utils.get_valmgr_ct()

    def setup_vmc_instance(self):
        self._vmc = t.ABIContract(
            self.tester_chain,
            self._vmc_abi,
            self._vmc_addr,
        )

    def get_block(self, block_number):
        block = self.tester_chain.chain.get_block_by_number(block_number)
        if block is None:
            raise ValueError("block {} is unavailable".format(block_number))
        return block.header

    def get_block_number(self):
        head_block = self.tester_chain.chain.head
        if head_block is None:
            raise ValueError("no block is available")
        return head_block.header.number

    def get_nonce(self, address):
        return self.tester_chain.head_state.get_nonce(address)

    def import_privkey(self, privkey):
        pass

    def is_vmc_deployed(self):
        state = self.tester_chain.head_state
        return (
            self.get_nonce(self._vmc_sender_addr) == 0 and \
            state.get_code(self._vmc_addr) != b''
        )

    def deploy_contract(self, bytecode, privkey):
        tx = contract_utils.create_contract_tx(self.tester_chain.head_state, privkey, bytecode)
        self.direct_tx(tx)

    def direct_tx(self, tx):
        return self.tester_chain.direct_tx(tx)

    def mine(self, number):
        self.tester_chain.mine(number)

    def unlock_account(self, account):
        pass

    # vmc related #############################

    def sample(self, shard_id):
        '''sample(shard_id: num) -> address
        '''
        return self._vmc.sample(shard_id, is_constant=True)

    def deposit(self, validation_code_addr, return_addr, privkey):
        '''deposit(validation_code_addr: address, return_addr: address) -> num
        '''
        result = self._vmc.deposit(
            validation_code_addr,
            return_addr,
            sender=privkey,
            value=sharding_config['DEPOSIT_SIZE'],
            startgas=510000,
        )

    def withdraw(self,
            validator_index,
            sig,
            privkey,
            gas=sharding_config['CONTRACT_CALL_GAS']['VALIDATOR_MANAGER']['withdraw']):
        '''withdraw(validator_index: num, sig: bytes <= 1000) -> bool
        '''
        result = self._vmc.withdraw(validator_index, sig, sender=privkey, startgas=510000)

    def get_shard_list(self):
        '''get_shard_list(valcode_addr: address) -> bool[100]
        '''
        raise NotImplementedError("Must be implemented by subclasses")

    def add_header(self, header, privkey):
        '''add_header(header: bytes <= 4096) -> bool
        '''
        return self._vmc.add_header(header, sender=privkey, startgas=510000)

    def get_period_start_prevhash(self, expected_period_number):
        '''get_period_start_prevhash(expected_period_number: num) -> bytes32
        '''
        return self._vmc.get_period_start_prevhash(expected_period_number, is_constant=True)

    def tx_to_shard(self, to, tx_startgas, tx_gasprice, data):
        '''tx_to_shard(
            to: address, shard_id: num, tx_startgas: num, tx_gasprice: num, data: bytes <= 4096
           ) -> num
        '''
        raise NotImplementedError("Must be implemented by subclasses")

    def get_collation_gas_limit(self):
        '''get_collation_gas_limit() -> num
        '''
        raise NotImplementedError("Must be implemented by subclasses")

    def get_collation_header_score(self, shard_id, collation_header_hash):
        return self._vmc.get_collation_headers__score(
            shard_id,
            collation_header_hash,
            is_constant=True,
        )

    def get_num_validators(self):
        return self._vmc.get_num_validators()


class RPCHandler(BaseChainHandler):

    PASSPHRASE = '123'

    def __init__(self, rpc_server_url='http://localhost:8545'):
        # self.init
        self._w3 = Web3(HTTPProvider(rpc_server_url))
        self.init_vmc_attributes()
        self.setup_vmc_instance()

    def init_vmc_attributes(self):
        self._vmc_addr = utils.checksum_encode(validator_manager_utils.get_valmgr_addr())
        print("!@# vmc_addr={}".format(self._vmc_addr))
        self._vmc_sender_addr = utils.checksum_encode(
            validator_manager_utils.get_valmgr_sender_addr(),
        )
        print("!@# vmc_sender_addr={}".format(self._vmc_sender_addr))
        self._vmc_bytecode = validator_manager_utils.get_valmgr_bytecode()
        self._vmc_code = validator_manager_utils.get_valmgr_code()
        self._vmc_abi = compiler.mk_full_signature(self._vmc_code)
        # print("!@# vmc_abi={}".format(self._vmc_abi))
        self._vmc_ct = validator_manager_utils.get_valmgr_ct()

    def setup_vmc_instance(self):
        self._vmc = self._w3.eth.contract(
            self._vmc_addr,
            abi=self._vmc_abi,
            bytecode=self._vmc_bytecode,
        )

    # RPC related

    def get_block(self, block_number):
        return self._w3.eth.getBlock(block_number)

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
        return (
            self._w3.eth.getCode(self._vmc_addr) != b'' and \
            self.get_nonce(self._vmc_sender_addr) != 0
        )

    def deploy_contract(self, bytecode, privkey):
        address = utils.privtoaddr(privkey)
        self.unlock_account(address)
        self._w3.eth.sendTransaction({"from": utils.checksum_encode(address), "data": bytecode})

    def direct_tx(self, tx):
        raw_tx = rlp.encode(tx)
        raw_tx_hex = self._w3.toHex(raw_tx)
        result = self._w3.eth.sendRawTransaction(raw_tx_hex)

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
            'value': sharding_config['DEPOSIT_SIZE'],
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
        self._vmc.transact({'from': address, 'gas': 510000}).withdraw(validator_index, sig)

    def add_header(self, header, privkey):
        '''add_header(header: bytes <= 4096) -> bool
        '''
        address = utils.checksum_encode(utils.privtoaddr(privkey))
        self.unlock_account(address)
        # print(self._vmc.call().add_header(header))
        self._vmc.transact({'from': address, 'gas': 510000}).add_header(header)

    def get_period_start_prevhash(self, expected_period_number):
        '''get_period_start_prevhash(expected_period_number: num) -> bytes32
        '''
        return self._vmc.call().get_period_start_prevhash(expected_period_number)

    def tx_to_shard(self, to, shard_id, tx_startgas, tx_gasprice, data):
        '''tx_to_shard(
            to: address, shard_id: num, tx_startgas: num, tx_gasprice: num, data: bytes <= 4096
           ) -> num
        '''
        pass

    def get_collation_gas_limit(self):
        '''get_collation_gas_limit() -> num
        '''
        return self._vmc.call().get_collation_gas_limit()

    def get_collation_header_score(self, shard_id, collation_header_hash):
        return self._vmc.call().get_collation_headers__score(shard_id, collation_header_hash)

    def get_num_validators(self):
        return self._vmc.call().get_num_validators()


def print_current_contract_address(sender_address, nonce):
    list_addresses = [
        utils.checksum_encode(utils.mk_contract_address(accounts[0], i)) for i in range(nonce + 1)
    ]
    print(list_addresses)


def import_tester_keys(handler):
    for privkey in keys:
        try:
            handler.import_privkey(privkey)
        except ValueError:
            pass


def first_setup_and_deposit(handler, validator_index):
    handler.deploy_valcode_and_deposit(validator_index)
    # TODO: error occurs when we don't mine so many blocks
    handler.mine(sharding_config['SHUFFLING_CYCLE_LENGTH'])


def do_withdraw(handler, validator_index):
    assert validator_index < len(keys)
    privkey = keys[validator_index]
    signature = contract_utils.sign(validator_manager_utils.WITHDRAW_HASH, privkey)
    handler.withdraw(validator_index, signature, privkey)
    handler.mine(1)


def get_testing_colhdr(
        handler,
        shard_id,
        parent_collation_hash,
        number,
        collation_coinbase=accounts[0],
        privkey=keys[0]):
    period_length = sharding_config['PERIOD_LENGTH']
    expected_period_number = (handler.get_block_number() + 1) // period_length
    print("!@# add_header: expected_period_number=", expected_period_number)
    period_start_prevhash = handler.get_period_start_prevhash(expected_period_number)
    print("!@# period_start_prevhash()={}".format(period_start_prevhash))
    tx_list_root = b"tx_list " * 4
    post_state_root = b"post_sta" * 4
    receipt_root = b"receipt " * 4
    sighash = utils.sha3(
        rlp.encode([
            shard_id,
            expected_period_number,
            period_start_prevhash,
            parent_collation_hash,
            tx_list_root,
            collation_coinbase,
            post_state_root,
            receipt_root,
            number,
        ])
    )
    sig = contract_utils.sign(sighash, privkey)
    # return rlp.encode([shard_id, sig])
    return rlp.encode([
        shard_id,
        expected_period_number,
        period_start_prevhash,
        parent_collation_hash,
        tx_list_root,
        collation_coinbase,
        post_state_root,
        receipt_root,
        number,
        sig,
    ])


def test_handler(HandlerClass):
    shard_id = 0
    validator_index = 0
    primary_key = keys[validator_index]
    primary_addr = accounts[validator_index]
    zero_addr = utils.checksum_encode(utils.int_to_addr(0))

    handler = HandlerClass()
    print(utils.checksum_encode(validator_manager_utils.viper_rlp_decoder_addr))
    print(utils.checksum_encode(validator_manager_utils.sighasher_addr))

    # print("!@# handler.get_block_number()={}".format(handler.get_block_number()))
    if not handler.is_vmc_deployed():
        import_tester_keys(handler)

        addr = utils.checksum_encode(primary_addr)
        print("!@# a0.addr={}".format(addr))
        handler.unlock_account(addr)
        handler.deploy_initiating_contracts(primary_key)
        handler.mine(1)

        first_setup_and_deposit(handler, validator_index)

    handler.mine(sharding_config['SHUFFLING_CYCLE_LENGTH'])
    # handler.deploy_valcode_and_deposit(validator_index); handler.mine(1)

    print("!@# sample(): ", handler.sample(0))
    print("!@# get_num_validators(): ", handler.get_num_validators())

    addr = utils.checksum_encode(primary_addr)
    handler.unlock_account(addr)

    genesis_colhdr_hash = utils.encode_int32(0)
    header1 = get_testing_colhdr(handler, shard_id, genesis_colhdr_hash, 1, privkey=primary_key)
    header1_hash = utils.sha3(header1)

    print("!@# add_header:", handler.add_header(header1, primary_key))
    handler.mine(sharding_config['SHUFFLING_CYCLE_LENGTH'])
    header2 = get_testing_colhdr(handler, shard_id, header1_hash, 2, privkey=primary_key)
    header2_hash = utils.sha3(header2)
    print("!@# sample(): ", handler.sample(shard_id))
    print("!@# add_header:", handler.add_header(header2, primary_key))
    handler.mine(sharding_config['SHUFFLING_CYCLE_LENGTH'])

    # do_withdraw(handler, validator_index)
    # handler.mine(1)
    print("!@# sample(): ", handler.sample(shard_id))
    print("!@# get_num_validators(): ", handler.get_num_validators())

    print("!@# get_collation_headers(shard_id, header_hash1)={}".format(
        handler.get_collation_header_score(shard_id, header1_hash)
    ))
    print("!@# get_collation_headers(shard_id, header_hash2)={}".format(
        handler.get_collation_header_score(shard_id, header2_hash)
    ))


if __name__ == '__main__':
    test_handler(TesterChainHandler)
    # test_handler(RPCHandler)
