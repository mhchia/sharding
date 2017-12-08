import time

from eth_tester import EthereumTester
from eth_tester.backends.pyevm import PyEVMBackend
import eth_utils
# from evm.exceptions import CanonicalHeadNotFound
import rlp
from web3 import Web3, HTTPProvider

from config import (
    DEFAULT_RPC_SERVER_URL,
    GASPRICE,
    PASSPHRASE,
    TX_GAS,
)

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

    # utils

    def deploy_contract(self, bytecode, address, value=0, gas=TX_GAS, gas_price=GASPRICE):
        raise NotImplementedError("Must be implemented by subclasses")

    def direct_tx(self, tx):
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

    def send_tx(self, sender_addr, to=None, value=0, data=b'', gas=TX_GAS, gas_price=GASPRICE):
        tx_obj = {
            'from': sender_addr,
            'value': value,
            'gas': gas,
            'gas_price': gas_price,
            'data': eth_utils.encode_hex(data),
        }
        if to is not None:
            tx_obj['to'] = to
        self.unlock_account(sender_addr)
        tx_hash = self.send_transaction(tx_obj)
        return tx_hash

    def deploy_contract(self, bytecode, address, value=0, gas=TX_GAS, gas_price=GASPRICE):
        return self.send_tx(address, value=value, data=bytecode, gas=gas, gas_price=gas_price)

    def direct_tx(self, tx):
        return self.et.backend.chain.apply_transaction(tx)


class RPCChainHandler(BaseChainHandler):

    def __init__(self, rpc_server_url=DEFAULT_RPC_SERVER_URL):
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

    def deploy_contract(self, bytecode, address, value=0, gas=TX_GAS, gas_price=GASPRICE):
        self.unlock_account(address)
        self.send_transaction({
            'from': address,
            'value': value,
            'gas': gas,
            'gas_price': gas_price,
            'data': bytecode,
        })

    def direct_tx(self, tx):
        raw_tx = rlp.encode(tx)
        raw_tx_hex = self._w3.toHex(raw_tx)
        tx_hash = self._w3.eth.sendRawTransaction(raw_tx_hex)
        return tx_hash
