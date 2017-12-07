import time

from eth_abi import (
    decode_abi,
    encode_abi,
)
from eth_tester import EthereumTester
from eth_tester.backends.pyevm import PyEVMBackend
from eth_tester.backends.pyevm.main import get_default_account_keys
from eth_tester.exceptions import ValidationError
from eth_tester.utils.accounts import generate_contract_address
import eth_utils
from evm.exceptions import CanonicalHeadNotFound
import rlp
from solc import compile_source
from viper import compiler
from web3 import Web3, HTTPProvider, TestRPCProvider
from web3.contract import ConciseContract

from sharding import (
    contract_utils,
    validator_manager_utils,
)
from sharding.config import sharding_config
from sharding import contract_utils

keys = get_default_account_keys()

sha3 = eth_utils.crypto.keccak

# FIXME: fix it, only for faster testing
sharding_config['SHUFFLING_CYCLE_LENGTH'] = 5

TX_GAS = 510000
GASPRICE = 1
PASSPHRASE = '123'

def get_func_abi(func_name, contract_abi):
    for func_abi in contract_abi:
        if func_abi['name'] == func_name:
            return func_abi
    raise ValueError('ABIof function {} not found in vmc'.format(func_name))

def mk_contract_tx_obj(
        func_name,
        args,
        contract_addr,
        contract_abi,
        sender_addr,
        value,
        gas,
        gas_price):
    # ct = validator_manager_utils.get_valmgr_ct()
    func_abi = get_func_abi(func_name, contract_abi)
    arg_types = [arg_abi['type'] for arg_abi in func_abi['inputs']]
    func_selector = eth_utils.function_abi_to_4byte_selector(func_abi)
    data = func_selector + encode_abi(arg_types, args)
    # data_old = validator_manager_utils.get_valmgr_ct().encode_function_call(func_name, args)
    data = eth_utils.encode_hex(data)
    print("!@# mk_contract_tx_obj: from={}, to={}".format(
            eth_utils.address.to_checksum_address(sender_addr),
            eth_utils.address.to_checksum_address(contract_addr),
        )
    )
    obj = {
        'from': eth_utils.address.to_checksum_address(sender_addr),
        'to': eth_utils.address.to_checksum_address(contract_addr),
        'value': value,
        'gas': gas,
        'gas_price': gas_price,
        'data': data,
    }
    return obj

def mk_vmc_tx_obj(
        func,
        args,
        sender_addr=keys[0].public_key.to_checksum_address(),
        value=0,
        gas=TX_GAS,
        gas_price=GASPRICE):
    vmc_abi = validator_manager_utils.get_valmgr_abi()
    vmc_addr = validator_manager_utils.get_valmgr_addr()
    return mk_contract_tx_obj(
        func,
        args,
        vmc_addr,
        vmc_abi,
        sender_addr,
        value,
        gas,
        gas_price,
    )

def decode_contract_call_result(func_name, contract_abi, result):
    func_abi = get_func_abi(func_name, contract_abi)
    output_types = [output_abi['type'] for output_abi in func_abi['outputs']]
    return decode_abi(output_types, result)[0]  # not sure why it's a tuple

def decode_vmc_call_result(func_name, result):
    vmc_abi = validator_manager_utils.get_valmgr_abi()
    return decode_contract_call_result(func_name, vmc_abi, result)


class BaseChainHandler:

    # RPC related

    def get_block_by_number(self, block_number):
        raise NotImplementedError("Must be implemented by subclasses")

    def get_block_number(self):
        raise NotImplementedError("Must be implemented by subclasses")

    def get_nonce(self, address):
        raise NotImplementedError("Must be implemented by subclasses")

    def import_privkey(self, privkey, passphrase=PASSPHRASE):
        raise NotImplementedError("Must be implemented by subclasses")

    def deploy_contract(self, bytecode, address):
        raise NotImplementedError("Must be implemented by subclasses")

    def direct_tx(self, tx):
        raise NotImplementedError("Must be implemented by subclasses")

    def mine(self, number):
        raise NotImplementedError("Must be implemented by subclasses")

    def unlock_account(self, account, passphrase=PASSPHRASE):
        raise NotImplementedError("Must be implemented by subclasses")

    def get_transaction_receipt(self, tx_hash):
        raise NotImplementedError("Must be implemented by subclasses")

    def send_transaction(self, tx_obj):
        raise NotImplementedError("Must be implemented by subclasses")

    def call(self, tx_obj):
        raise NotImplementedError("Must be implemented by subclasses")


class TesterChainHandler(BaseChainHandler):

    def __init__(self):
        self.et = EthereumTester(backend=PyEVMBackend(), auto_mine_transactions=False)

    def get_block_by_number(self, block_number):
        block = self.et.get_block_by_number(block_number)
        return block

    def get_block_number(self):
        # raise CanonicalHeadNotFound if head is not found
        head_block_header = self.et.backend.chain.get_canonical_head()
        return head_block_header.block_number

    def get_nonce(self, address):
        return self.et.get_nonce(address)

    def import_privkey(self, privkey, passphrase=PASSPHRASE):
        self.et.add_account(privkey, passphrase)

    def mine(self, number):
        self.et.mine_blocks(num_blocks=number)

    def unlock_account(self, account, passphrase=PASSPHRASE):
        # self.et.unlock_account(account, passphrase)
        pass

    def get_transaction_receipt(self, tx_hash):
        return self.et.get_transaction_receipt(tx_hash)

    def send_transaction(self, tx_obj):
        return self.et.send_transaction(tx_obj)

    def call(self, tx_obj):
        return self.et.call(tx_obj)

    # utils

    def send_tx(self, sender_addr, to=None, value=0, data=b'', gas=TX_GAS, gasprice=GASPRICE):
        tx_obj = {
            'from': sender_addr,
            'value': value,
            'gas': gas,
            'gas_price': gasprice,
            'data': eth_utils.encode_hex(data),
        }
        if to is not None:
            tx_obj['to'] = to
        self.unlock_account(sender_addr)
        tx_hash = self.send_transaction(tx_obj)
        return tx_hash

    def deploy_contract(self, bytecode, address):
        return self.send_tx(address, value=0, data=bytecode)

    def direct_tx(self, tx):
        # FIXME: hacky
        from ethereum.transactions import Transaction
        if isinstance(tx, Transaction):
            from evm.vm.forks.spurious_dragon.transactions import SpuriousDragonTransaction
            evm_tx = SpuriousDragonTransaction(
                tx.nonce,
                tx.gasprice,
                tx.startgas,
                tx.to,
                tx.value,
                tx.data,
                tx.v,
                tx.r,
                tx.s,
            )
        else:
            evm_tx = tx
        # FIXME: hacky
        return self.et.backend.chain.apply_transaction(evm_tx)


class RPCHandler(BaseChainHandler):

    def __init__(self, rpc_server_url='http://localhost:8545'):
        # self.init
        self._w3 = Web3(HTTPProvider(rpc_server_url))

    # RPC related

    def get_block_by_number(self, block_number):
        return self._w3.eth.getBlock(block_number)

    def get_block_number(self):
        return self._w3.eth.blockNumber

    def get_code(self, address):
        return self._w3.eth.getCode(address)

    def get_nonce(self, address):
        return self._w3.eth.getTransactionCount(address)

    def import_privkey(self, privkey, passphrase=PASSPHRASE):
        '''
            @privkey: bytes
        '''
        self._w3.personal.importRawKey(privkey, passphrase)

    def mine(self, number):
        '''
        '''
        expected_block_number = self.get_block_number() + number
        self._w3.miner.start(1)
        while self.get_block_number() < expected_block_number:
            time.sleep(0.1)
        self._w3.miner.stop()

    def unlock_account(self, account, passphrase=PASSPHRASE):
        account = eth_utils.address.to_checksum_address(account)
        self._w3.personal.unlockAccount(account, passphrase)

    def get_transaction_receipt(self, tx_hash):
        return self._w3.eth.getTransactionReceipt(tx_hash)

    def send_transaction(self, tx_obj):
        return self._w3.eth.sendTransaction(tx_obj)

    def call(self, tx_obj):
        return self._w3.eth.call(tx_obj)

    # utils

    def deploy_contract(self, bytecode, address):
        self.unlock_account(address)
        self.send_transaction(
            {"from": address, "data": bytecode}
        )

    def direct_tx(self, tx):
        raw_tx = rlp.encode(tx)
        raw_tx_hex = self._w3.toHex(raw_tx)
        tx_hash = self._w3.eth.sendRawTransaction(raw_tx_hex)
        return tx_hash


class VMCHandler:

    def __init__(self, chain_handler=TesterChainHandler()):
        self.chain_handler = chain_handler
        self.init_vmc_attributes()

    def init_vmc_attributes(self):
        self._vmc_addr = eth_utils.address.to_checksum_address(
            validator_manager_utils.get_valmgr_addr()
        )
        print("!@# vmc_addr={}".format(self._vmc_addr))
        self._vmc_sender_addr = eth_utils.address.to_checksum_address(
            validator_manager_utils.get_valmgr_sender_addr()
        )
        print("!@# vmc_sender_addr={}".format(self._vmc_sender_addr))
        self._vmc_bytecode = validator_manager_utils.get_valmgr_bytecode()
        self._vmc_code = validator_manager_utils.get_valmgr_code()
        self._vmc_abi = compiler.mk_full_signature(self._vmc_code)
        # print("!@# vmc_abi={}".format(self._vmc_abi))
        self._vmc_ct = validator_manager_utils.get_valmgr_ct()

    # vmc utils ####################################

    def call_vmc(
            self,
            func_name,
            args,
            sender_addr=keys[0].public_key.to_checksum_address(),
            value=0,
            gas=TX_GAS,
            gas_price=GASPRICE):
        tx_obj = mk_vmc_tx_obj(func_name, args, sender_addr, value, gas, gas_price)
        result = self.chain_handler.call(tx_obj)
        decoded_result = decode_vmc_call_result(func_name, result)
        print("!@# call_vmc: func_name={}, args={}, result={}".format(
            func_name,
            args,
            decoded_result,
        ))
        return decoded_result

    def send_vmc_tx(
            self,
            func_name,
            args,
            sender_addr=keys[0].public_key.to_checksum_address(),
            value=0,
            gas=TX_GAS,
            gas_price=GASPRICE):
        tx_obj = mk_vmc_tx_obj(func_name, args, sender_addr, value, gas, gas_price)
        tx_hash = self.chain_handler.send_transaction(tx_obj)
        print("!@# send_vmc_tx: func_name={}, args={}, tx_hash={}".format(
            func_name,
            args,
            tx_hash,
        ))
        return tx_hash

    # vmc related #############################

    def sample(self, shard_id):
        '''sample(shard_id: num) -> address
        '''
        return self.call_vmc('sample', [shard_id])

    def deposit(
            self,
            validation_code_addr,
            return_addr,
            sender_addr,
            gas=TX_GAS,
            gas_price=GASPRICE):
        '''deposit(validation_code_addr: address, return_addr: address) -> num
        '''
        return self.send_vmc_tx(
            'deposit',
            [validation_code_addr, return_addr],
            sender_addr=sender_addr,
            gas=gas,
            gas_price=gas_price,
            value=sharding_config['DEPOSIT_SIZE'],
        )

    def withdraw(self, validator_index, sig, sender_addr, gas=TX_GAS, gas_price=GASPRICE):
        '''withdraw(validator_index: num, sig: bytes <= 1000) -> bool
        '''
        return self.send_vmc_tx(
            'withdraw',
            [validator_index, sig],
            sender_addr=sender_addr,
            gas=gas,
            gas_price=gas_price,
        )

    def get_shard_list(self, valcode_addr):
        '''get_shard_list(valcode_addr: address) -> bool[100]
        '''
        return self.call_vmc('get_shard_list', [valcode_addr])

    def add_header(self, header, sender_addr, gas=TX_GAS, gas_price=GASPRICE):
        '''add_header(header: bytes <= 4096) -> bool
        '''
        return self.send_vmc_tx(
            'add_header',
            [header],
            sender_addr=sender_addr,
            gas=gas,
            gas_price=gas_price,
        )

    def get_period_start_prevhash(self, expected_period_number):
        '''get_period_start_prevhash(expected_period_number: num) -> bytes32
        '''
        return self.call_vmc('get_period_start_prevhash', [expected_period_number])

    def tx_to_shard(
            self,
            to,
            shard_id,
            tx_startgas,
            tx_gasprice,
            data,
            value,
            sender_addr,
            gas=TX_GAS,
            gas_price=GASPRICE):
        '''tx_to_shard(
            to: address, shard_id: num, tx_startgas: num, tx_gasprice: num, data: bytes <= 4096
           ) -> num
        '''
        return self.send_vmc_tx(
            'tx_to_shard',
            [to, shard_id, tx_startgas, tx_gasprice, data],
            sender_addr=sender_addr,
            gas=gas,
            gas_price=gas_price,
            value=value,
        )

    def get_collation_gas_limit(self):
        '''get_collation_gas_limit() -> num
        '''
        return self.call_vmc('get_collation_gas_limit', [])

    def get_collation_header_score(self, shard_id, collation_header_hash):
        return self.call_vmc('get_collation_headers__score', [shard_id, collation_header_hash])

    def get_num_validators(self):
        return self.call_vmc('get_num_validators', [])

    def get_receipt_value(self, receipt_id):
        return self.call_vmc('get_receipts__value', [receipt_id])

    # utils #######################################################

    def is_vmc_deployed(self):
        return (
            # self.chain_handler.get_code(self._vmc_addr) != b'' and \
            self.chain_handler.get_nonce(self._vmc_sender_addr) != 0
        )

    def deploy_valcode_and_deposit(self, validator_index):
        privkey = keys[validator_index]
        address = privkey.public_key.to_checksum_address()
        self.chain_handler.unlock_account(address)
        valcode = validator_manager_utils.mk_validation_code(
            privkey.public_key.to_canonical_address()
        )
        nonce = self.chain_handler.get_nonce(address)
        valcode_addr = eth_utils.address.to_checksum_address(
            generate_contract_address(address, nonce)
        )
        self.chain_handler.unlock_account(address)
        self.chain_handler.deploy_contract(valcode, address)
        self.chain_handler.mine(1)
        self.deposit(valcode_addr, address, address)

    def deploy_initiating_contracts(self, privkey):
        if not self.is_vmc_deployed():
            addr = privkey.public_key.to_checksum_address()
            self.chain_handler.unlock_account(addr)
            nonce = self.chain_handler.get_nonce(addr)
            txs = validator_manager_utils.mk_initiating_contracts(privkey.to_bytes(), nonce)
            for tx in txs[:3]:
                self.chain_handler.direct_tx(tx)
            self.chain_handler.mine(1)
            for tx in txs[3:]:
                self.chain_handler.direct_tx(tx)
                self.chain_handler.mine(1)
            print(
                '!@# deploy: vmc: ',
                self.chain_handler.get_transaction_receipt(eth_utils.encode_hex(txs[-1].hash)),
            )

    def first_setup_and_deposit(self, validator_index):
        self.deploy_valcode_and_deposit(validator_index)
        # TODO: error occurs when we don't mine so many blocks
        self.chain_handler.mine(sharding_config['SHUFFLING_CYCLE_LENGTH'])

    def import_key_to_chain_handler(self, key):
        try:
            self.chain_handler.import_privkey(key.to_hex())
        except (ValueError, ValidationError):
            pass


def print_current_contract_address(sender_address, nonce):
    list_addresses = [
        eth_utils.address.to_checksum_address(
            generate_contract_address(keys[0].public_key.to_checksum_address(), i)
        ) for i in range(nonce + 1)
    ]
    print(list_addresses)

def do_withdraw(vmc_handler, validator_index):
    assert validator_index < len(keys)
    privkey = keys[validator_index]
    signature = contract_utils.sign(validator_manager_utils.WITHDRAW_HASH, privkey)
    vmc_handler.withdraw(validator_index, signature, privkey)
    vmc_handler.chain_handler.mine(1)

def get_testing_colhdr(
        vmc_handler,
        shard_id,
        parent_collation_hash,
        number,
        collation_coinbase=keys[0].public_key.to_canonical_address(),
        privkey=keys[0].to_bytes()):
    period_length = sharding_config['PERIOD_LENGTH']
    expected_period_number = (vmc_handler.chain_handler.get_block_number() + 1) // period_length
    print("!@# add_header: expected_period_number=", expected_period_number)
    period_start_prevhash = vmc_handler.get_period_start_prevhash(expected_period_number)
    print("!@# period_start_prevhash()={}".format(period_start_prevhash))
    tx_list_root = b"tx_list " * 4
    post_state_root = b"post_sta" * 4
    receipt_root = b"receipt " * 4
    sighash = sha3(
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


def test_handler(ChainHandlerClass):
    shard_id = 0
    validator_index = 0
    primary_key = keys[validator_index].to_hex()
    primary_addr = keys[validator_index].public_key.to_checksum_address()
    zero_addr = eth_utils.address.to_checksum_address(b'\x00' * 20)

    vmc_handler = VMCHandler(ChainHandlerClass())
    print(eth_utils.address.to_checksum_address(validator_manager_utils.viper_rlp_decoder_addr))
    print(eth_utils.address.to_checksum_address(validator_manager_utils.sighasher_addr))

    # print("!@# handler.get_block_number()={}".format(handler.get_block_number()))
    if not vmc_handler.is_vmc_deployed():
        print('not handler.is_vmc_deployed()')
        # import privkey
        for key in keys:
            vmc_handler.import_key_to_chain_handler(key)

        vmc_handler.deploy_initiating_contracts(keys[validator_index])
        vmc_handler.chain_handler.mine(1)
        vmc_handler.first_setup_and_deposit(validator_index)

    assert vmc_handler.is_vmc_deployed()

    vmc_handler.chain_handler.mine(sharding_config['SHUFFLING_CYCLE_LENGTH'])
    # handler.deploy_valcode_and_deposit(validator_index); handler.mine(1)

    assert vmc_handler.sample(0) != zero_addr
    assert vmc_handler.get_num_validators() == 1
    print("!@# get_num_validators(): ", vmc_handler.get_num_validators())

    addr = eth_utils.address.to_checksum_address(primary_addr)

    genesis_colhdr_hash = b'\x00' * 32
    header1 = get_testing_colhdr(vmc_handler, shard_id, genesis_colhdr_hash, 1)
    header1_hash = sha3(header1)
    vmc_handler.add_header(header1, primary_addr)
    vmc_handler.chain_handler.mine(sharding_config['SHUFFLING_CYCLE_LENGTH'])

    header2 = get_testing_colhdr(vmc_handler, shard_id, header1_hash, 2)
    header2_hash = sha3(header2)
    vmc_handler.add_header(header2, primary_addr)
    vmc_handler.chain_handler.mine(sharding_config['SHUFFLING_CYCLE_LENGTH'])

    assert vmc_handler.get_collation_header_score(shard_id, header1_hash) == 1
    assert vmc_handler.get_collation_header_score(shard_id, header2_hash) == 2

    vmc_handler.tx_to_shard(
        keys[1].public_key.to_checksum_address(),
        shard_id,
        100000,
        1,
        b'',
        1234567,
        primary_addr,
    )
    vmc_handler.chain_handler.mine(1)
    assert vmc_handler.get_receipt_value(0) == 1234567


def test_contract(ChainHandlerClass):
    chain_handler = ChainHandlerClass()
    chain_handler.mine(1)
    code = """
num_test: public(num)

@public
def __init__():
    self.num_test = 42

@public
def update_num_test(_num_test: num):
    self.num_test = _num_test
"""
    bytecode = compiler.compile(code)
    abi = compiler.mk_full_signature(code)
    sender_addr = keys[0].public_key.to_checksum_address()
    print(handler.get_nonce(sender_addr))
    contract_addr = eth_utils.address.to_checksum_address(
        generate_contract_address(sender_addr, handler.get_nonce(sender_addr))
    )
    print("contract_addr={}".format(contract_addr))
    tx_hash = chain_handler.deploy_contract(bytecode, sender_addr)
    chain_handler.mine(1)
    print(tx_hash)
    assert contract_addr == handler.et.get_transaction_receipt(tx_hash)['contract_address']
    tx_obj = mk_contract_tx_obj('get_num_test', [], contract_addr, abi, sender_addr, 0, 50000, 1)
    print(handler.et.call(tx_obj))
    # tx_hash = chain_handler.send_transaction(tx_obj)
    chain_handler.mine(1)

    tx_obj = mk_contract_tx_obj('update_num_test', [4], contract_addr, abi, sender_addr, 0, 50000, 1)
    tx_hash = chain_handler.send_transaction(tx_obj)
    chain_handler.mine(1)

    tx_obj = mk_contract_tx_obj('get_num_test', [], contract_addr, abi, sender_addr, 0, 50000, 1)
    print(chain_handler.call(tx_obj))


if __name__ == '__main__':
    test_handler(TesterChainHandler)
    # test_handler(RPCHandler)
    # test_contract(TesterChainHandler)
